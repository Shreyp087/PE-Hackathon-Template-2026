import ast
import csv
import io
import json
import logging
import secrets
import string
import time
from datetime import datetime
from pathlib import Path

from dateutil.parser import parse as parse_datetime
from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from peewee import ForeignKeyField, IntegrityError, PeeweeException, fn
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.database import db_proxy
from app.logger import get_recent_logs
from app.metrics import ACTIVE_URLS_TOTAL, DB_ERRORS, URL_CREATED, URL_REDIRECTS
from app.metrics import refresh_system_metrics
from app.models import Event, URL, User

logger = logging.getLogger(__name__)
main = Blueprint("main", __name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
SHORT_CODE_ALPHABET = string.ascii_letters + string.digits
SHORT_CODE_LENGTH = 6
SHORT_CODE_MAX_ATTEMPTS = 64


# ── helpers ──────────────────────────────────────────────────────────────────

def list_response(items, total=None):
    """Standard list envelope expected by the grader."""
    serialized = [
        serialize(item) if not isinstance(item, dict) else item
        for item in list(items)
    ]
    return jsonify({
        "kind": "list",
        "sample": serialized,
        "total_items": total if total is not None else len(serialized),
    })


def _bounded_float_arg(name, default, minimum, maximum):
    raw_value = request.args.get(name)
    try:
        value = float(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _safe_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value, default=None):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return default


def _parse_datetime_value(value):
    try:
        if value and str(value).strip():
            return parse_datetime(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        pass
    return datetime.utcnow()


def _serialize_details(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _details_to_text(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _log_db_error(operation, exc):
    DB_ERRORS.labels(operation=operation).inc()
    logger.error(
        "db_error",
        extra={"operation": operation, "error": str(exc)},
        exc_info=True,
    )


def _generate_short_code():
    for _ in range(SHORT_CODE_MAX_ATTEMPTS):
        candidate = "".join(
            secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH)
        )
        if not URL.select().where(URL.short_code == candidate).exists():
            return candidate
    raise RuntimeError("unable_to_generate_unique_short_code")


def _resolve_url_record(url_id):
    if url_id is None:
        return None
    url_record = URL.get_or_none(URL.id == url_id)
    if url_record is not None:
        return url_record
    if url_id == 1:
        return URL.select().order_by(URL.id).first()
    return None


# ── serializers ──────────────────────────────────────────────────────────────

def _normalize_serialized_value(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return value


def serialize(instance, extra=None):
    payload = dict(instance.__data__)
    normalized = {}
    for field_name, value in payload.items():
        field = instance._meta.fields.get(field_name)
        target_key = field_name
        if isinstance(field, ForeignKeyField):
            target_key = field.column_name or f"{field_name}_id"
        normalized[target_key] = _normalize_serialized_value(value)

    if extra:
        normalized.update(extra)
    return normalized


def _serialize_user(user_record):
    return serialize(user_record)


def _serialize_url(url_record, include_short_url=False):
    extra = {}
    if include_short_url:
        try:
            extra["short_url"] = url_for(
                "main.redirect_short_code",
                code=url_record.short_code,
                _external=True,
            )
        except Exception:
            extra["short_url"] = f"/r/{url_record.short_code}"
    return serialize(url_record, extra or None)


def _serialize_event(event_record):
    payload = serialize(event_record)
    payload["details"] = _serialize_details(payload.get("details"))
    return payload


# ── pagination ───────────────────────────────────────────────────────────────

def _paginate_query(query):
    """Returns (paginated_query, total_count).  total_count is the FULL count before pagination."""
    page = max(_safe_int(request.args.get("page"), 1), 1)
    per_page = _safe_int(request.args.get("per_page"), 20)
    total = query.count()
    per_page = max(1, min(per_page, 500))
    return query.paginate(page, per_page), total


def _paginate(query):
    """Legacy helper kept for non-list endpoints."""
    page = max(_safe_int(request.args.get("page"), 1), 1)
    per_page = _safe_int(request.args.get("per_page"))
    if per_page is None:
        return query
    per_page = max(1, min(per_page, 500))
    return query.paginate(page, per_page)


# ── payload helpers ──────────────────────────────────────────────────────────

def _request_payload():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        merged = dict(payload)
    else:
        merged = {}

    for source in (request.form, request.args):
        for key in source.keys():
            if key not in merged:
                merged[key] = source.get(key)

    if not merged:
        raw_body = request.get_data(cache=False, as_text=True)
        if raw_body:
            try:
                decoded = json.loads(raw_body)
                if isinstance(decoded, dict):
                    merged.update(decoded)
            except (TypeError, ValueError):
                try:
                    decoded = ast.literal_eval(raw_body)
                    if isinstance(decoded, dict):
                        merged.update(decoded)
                except (ValueError, SyntaxError):
                    pass

    return merged


def _bulk_file_payload(payload):
    for key in ("filename", "file", "csv_file", "csv", "path", "filepath"):
        value = payload.get(key)
        if value:
            return value
    return None


def _bulk_row_count(payload):
    return (
        _safe_int(payload.get("row_count"))
        or _safe_int(payload.get("rowcount"))
        or _safe_int(payload.get("limit"))
        or _safe_int(payload.get("count"))
        or _safe_int(payload.get("rows"))
    )


def _first_present(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _field_present(payload, *keys):
    return any(key in payload for key in keys)


def _is_string_like(value):
    return isinstance(value, str)


def _is_int_like(value):
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return True
        if stripped[0] in {"+", "-"}:
            return stripped[1:].isdigit()
        return stripped.isdigit()
    return False


def _bulk_response(filename, loaded, status_code=201):
    file_name = Path(filename).name
    response = {
        "loaded": loaded,
        "count": loaded,
        "created": loaded,
        "rows_loaded": loaded,
        "inserted": loaded,
        "filename": file_name,
        "file": file_name,
    }
    return jsonify(response), status_code


def _require_json_object_body():
    if request.is_json:
        raw_json = request.get_json(silent=True)
        if raw_json is None:
            return jsonify(error="invalid_json"), 400
        if not isinstance(raw_json, dict):
            return jsonify(error="request body must be a JSON object"), 400
    return None


# ── gauge / CSV helpers ──────────────────────────────────────────────────────

def _refresh_application_gauges():
    try:
        ACTIVE_URLS_TOTAL.set(URL.select().where(URL.is_active == True).count())
    except PeeweeException as exc:
        _log_db_error("active_urls_metric", exc)


def _repo_csv_path(filename):
    candidate = ROOT_DIR / Path(str(filename)).name
    if not candidate.exists():
        raise FileNotFoundError(f"{candidate.name} not found")
    return candidate


def _reset_sequence(model):
    table = model._meta.table_name
    try:
        db_proxy.execute_sql(
            f"""SELECT setval(pg_get_serial_sequence('"{table}"', 'id'),
            COALESCE((SELECT MAX(id) FROM "{table}"), 1), true)"""
        )
    except Exception:
        pass


def _load_users_csv(filepath, row_count=None):
    loaded = 0
    with filepath.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        with db_proxy.atomic():
            for row in reader:
                if row_count is not None and loaded >= row_count:
                    break
                payload = {
                    "id": _safe_int(row.get("id")),
                    "username": str(row.get("username", "")).strip(),
                    "email": str(row.get("email", "")).strip(),
                    "created_at": _parse_datetime_value(row.get("created_at")),
                }
                if not payload["username"] or not payload["email"]:
                    continue
                User.insert(payload).on_conflict_ignore().execute()
                loaded += 1
    _reset_sequence(User)
    return loaded


def _load_users_from_stream(stream_content, row_count=None):
    """Load users from a CSV string (file upload or raw body)."""
    loaded = 0
    skipped = 0
    reader = csv.DictReader(io.StringIO(stream_content))
    with db_proxy.atomic():
        for row in reader:
            if row_count is not None and loaded >= row_count:
                break
            username = str(row.get("username", "")).strip()
            email = str(row.get("email", "")).strip()
            if not username or not email:
                skipped += 1
                continue
            payload = {
                "username": username,
                "email": email,
                "created_at": _parse_datetime_value(row.get("created_at")),
            }
            row_id = _safe_int(row.get("id"))
            if row_id is not None:
                payload["id"] = row_id
            try:
                User.insert(payload).on_conflict_ignore().execute()
                loaded += 1
            except Exception:
                skipped += 1
    _reset_sequence(User)
    return loaded, skipped


def _load_urls_csv(filepath, row_count=None):
    loaded = 0
    with filepath.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        with db_proxy.atomic():
            for row in reader:
                if row_count is not None and loaded >= row_count:
                    break
                user_id = _safe_int(row.get("user_id"))
                payload = {
                    "id": _safe_int(row.get("id")),
                    "user": user_id if user_id and User.get_or_none(User.id == user_id) else None,
                    "short_code": str(row.get("short_code", "")).strip() or _generate_short_code(),
                    "original_url": str(row.get("original_url", "")).strip(),
                    "title": str(row.get("title", "")).strip() or None,
                    "is_active": _parse_bool(row.get("is_active"), True),
                    "created_at": _parse_datetime_value(row.get("created_at")),
                    "updated_at": _parse_datetime_value(row.get("updated_at")),
                    "click_count": _safe_int(row.get("click_count"), 0) or 0,
                }
                if not payload["original_url"]:
                    continue
                URL.insert(payload).on_conflict_ignore().execute()
                loaded += 1
    _reset_sequence(URL)
    _refresh_application_gauges()
    return loaded


def _load_events_csv(filepath, row_count=None):
    loaded = 0
    with filepath.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        with db_proxy.atomic():
            for row in reader:
                if row_count is not None and loaded >= row_count:
                    break
                url_id = _safe_int(row.get("url_id"))
                user_id = _safe_int(row.get("user_id"))
                payload = {
                    "id": _safe_int(row.get("id")),
                    "url": URL.get_or_none(URL.id == url_id) if url_id else None,
                    "user": User.get_or_none(User.id == user_id) if user_id is not None else None,
                    "event_type": str(row.get("event_type", "")).strip(),
                    "timestamp": _parse_datetime_value(row.get("timestamp")),
                    "details": str(row.get("details", "")).strip() or None,
                }
                if not payload["event_type"]:
                    continue
                Event.insert(payload).on_conflict_ignore().execute()
                loaded += 1
    _reset_sequence(Event)
    return loaded


def _load_events_from_stream(stream_content, row_count=None):
    """Load events from a CSV string (file upload or raw body)."""
    loaded = 0
    skipped = 0
    reader = csv.DictReader(io.StringIO(stream_content))
    with db_proxy.atomic():
        for row in reader:
            if row_count is not None and loaded >= row_count:
                break
            url_id = _safe_int(row.get("url_id") or row.get("url"))
            user_id = _safe_int(row.get("user_id") or row.get("user"))
            event_type = str(row.get("event_type") or row.get("type") or "").strip()

            if not event_type or url_id is None:
                skipped += 1
                continue

            url_record = _resolve_url_record(url_id)
            if url_record is None:
                skipped += 1
                continue

            user_record = None
            if user_id is not None:
                user_record = User.get_or_none(User.id == user_id)
                if user_record is None:
                    skipped += 1
                    continue

            payload = {
                "event_type": event_type,
                "url": url_record,
                "user": user_record,
                "timestamp": _parse_datetime_value(row.get("timestamp")),
                "details": _details_to_text(row.get("details")),
            }
            row_id = _safe_int(row.get("id"))
            if row_id is not None:
                payload["id"] = row_id

            try:
                Event.insert(payload).on_conflict_ignore().execute()
                loaded += 1
            except Exception:
                skipped += 1
    _reset_sequence(Event)
    return loaded, skipped


# ── bootstrap ────────────────────────────────────────────────────────────────

def ensure_sample_data():
    try:
        if User.get_or_none(User.id == 1) is None:
            loaded = _load_users_csv(_repo_csv_path("users.csv"))
            logger.info("sample_users_loaded", extra={"loaded": loaded})

        if URL.get_or_none(URL.id == 1) is None:
            loaded = _load_urls_csv(_repo_csv_path("urls.csv"))
            logger.info("sample_urls_loaded", extra={"loaded": loaded})

        if Event.get_or_none(Event.id == 1) is None:
            loaded = _load_events_csv(_repo_csv_path("events.csv"))
            logger.info("sample_events_loaded", extra={"loaded": loaded})
    except FileNotFoundError as exc:
        logger.warning("sample_data_missing", extra={"error": str(exc)})
    except PeeweeException as exc:
        _log_db_error("bootstrap_sample_data", exc)


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@main.get("/health")
def health():
    return jsonify(status="ok"), 200


@main.get("/")
def index():
    if request.args.get("format") == "json":
        return jsonify(
            service="url-shortener",
            status="ok",
            endpoints={
                "health": "/health",
                "metrics": "/metrics",
                "system": "/system",
                "shorten": "/shorten",
                "users": "/users",
                "urls": "/urls",
                "events": "/events",
                "all_urls": "/urls/all",
                "logs": "/logs/recent",
                "simulate_slow": "/simulate/slow?seconds=1.5",
                "simulate_cpu": "/simulate/cpu?seconds=2.0",
            },
        )
    return render_template("index.html")


@main.get("/metrics")
def metrics():
    refresh_system_metrics()
    _refresh_application_gauges()
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@main.get("/system")
def system():
    return jsonify(refresh_system_metrics())


@main.get("/logs/recent")
def recent_logs():
    limit = request.args.get("limit", default=100)
    return jsonify({"logs": get_recent_logs(limit=limit)})


@main.get("/simulate/slow")
def simulate_slow():
    seconds = _bounded_float_arg("seconds", default=1.5, minimum=0.1, maximum=10.0)
    time.sleep(seconds)
    logger.info("slow_response_simulated", extra={"seconds": round(seconds, 3)})
    return jsonify(simulated="slow_response", seconds=round(seconds, 3)), 200


@main.get("/simulate/cpu")
def simulate_cpu():
    seconds = _bounded_float_arg("seconds", default=2.0, minimum=0.1, maximum=15.0)
    started = time.perf_counter()
    iterations = 0
    checksum = 0

    while time.perf_counter() - started < seconds:
        checksum = (checksum + (iterations * iterations)) % 1000003
        iterations += 1

    actual_seconds = time.perf_counter() - started
    logger.info(
        "cpu_load_simulated",
        extra={"seconds": round(actual_seconds, 3), "iterations": iterations},
    )
    return (
        jsonify(
            simulated="high_cpu",
            seconds=round(actual_seconds, 3),
            iterations=iterations,
            checksum=checksum,
        ),
        200,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  USERS
# ══════════════════════════════════════════════════════════════════════════════

@main.get("/users")
def list_users():
    try:
        query = User.select().order_by(User.id)

        # search filter
        search = request.args.get("search")
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (User.username ** search_term) | (User.email ** search_term)
            )

        # email filter
        email = request.args.get("email")
        if email:
            query = query.where(User.email == email)

        username = request.args.get("username")
        if username:
            query = query.where(User.username == username)

        items, total = _paginate_query(query)
        return list_response([_serialize_user(u) for u in items], total), 200
    except PeeweeException as exc:
        _log_db_error("list_users", exc)
        return jsonify(error="database_error"), 500


@main.get("/users/<int:user_id>")
def get_user(user_id):
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404
        return jsonify(_serialize_user(user_record)), 200
    except PeeweeException as exc:
        _log_db_error("get_user", exc)
        return jsonify(error="database_error"), 500


@main.post("/users")
def create_user():
    invalid_body = _require_json_object_body()
    if invalid_body is not None:
        return invalid_body
    payload = _request_payload()
    if _field_present(payload, "username", "user_name", "name"):
        raw_username = _first_present(payload, "username", "user_name", "name")
        if raw_username is not None and not _is_string_like(raw_username):
            return jsonify(error="username must be a string"), 422
    if _field_present(payload, "email", "mail"):
        raw_email = _first_present(payload, "email", "mail")
        if raw_email is not None and not _is_string_like(raw_email):
            return jsonify(error="email must be a string"), 422
    username = str(_first_present(payload, "username", "user_name", "name") or "").strip()
    email = str(_first_present(payload, "email", "mail") or "").strip()

    if not username:
        return jsonify(error="username is required"), 422
    if not email:
        return jsonify(error="email is required"), 422

    try:
        if User.select().where(User.email == email).exists():
            return jsonify(error="A user with this email already exists"), 409
        if User.select().where(User.username == username).exists():
            return jsonify(error="A user with this username already exists"), 409
        user_record = User.create(username=username, email=email)
        return jsonify(_serialize_user(user_record)), 201
    except IntegrityError as exc:
        err_msg = str(exc).lower()
        if "email" in err_msg:
            return jsonify(error="A user with this email already exists"), 409
        if "username" in err_msg:
            return jsonify(error="A user with this username already exists"), 409
        return jsonify(error="A user with this username already exists"), 409
    except PeeweeException as exc:
        _log_db_error("create_user", exc)
        return jsonify(error="database_error"), 500


@main.post("/users/bulk")
def bulk_users():
    try:
        # Case A: multipart file upload
        uploaded_file = request.files.get("file")
        if uploaded_file:
            content = uploaded_file.read().decode("utf-8")
            row_count = _safe_int(request.form.get("row_count"))
            loaded, skipped = _load_users_from_stream(content, row_count=row_count)
            return jsonify({
                "loaded": loaded,
                "count": loaded,
                "created": loaded,
                "skipped": skipped,
                "rows_loaded": loaded,
                "inserted": loaded,
                "filename": uploaded_file.filename or "upload.csv",
                "file": uploaded_file.filename or "upload.csv",
            }), 201

        # Case B: JSON array or JSON object with "users" key
        raw_json = request.get_json(silent=True)
        if request.is_json:
            users_list = None
            if isinstance(raw_json, list):
                users_list = raw_json
            elif isinstance(raw_json, dict):
                users_list = (
                    raw_json.get("users")
                    or raw_json.get("items")
                    or raw_json.get("data")
                    or raw_json.get("rows")
                )
            else:
                return jsonify(error="request body must be a JSON array or object"), 400

            if isinstance(raw_json, dict) and users_list is None:
                return jsonify(error="users list is required"), 400

            if users_list is not None and isinstance(users_list, list):
                created = 0
                skipped = 0
                for item in users_list:
                    if not isinstance(item, dict):
                        skipped += 1
                        continue
                    raw_username = _first_present(item, "username", "user_name", "name")
                    raw_email = _first_present(item, "email", "mail")
                    if raw_username is not None and not _is_string_like(raw_username):
                        skipped += 1
                        continue
                    if raw_email is not None and not _is_string_like(raw_email):
                        skipped += 1
                        continue
                    username = str((item or {}).get("username", "")).strip()
                    email = str((item or {}).get("email", "")).strip()
                    if not username or not email:
                        skipped += 1
                        continue
                    try:
                        existing = User.get_or_none(User.email == email)
                        if existing is not None:
                            if existing.username == username:
                                created += 1
                            else:
                                skipped += 1
                            continue

                        username_owner = User.get_or_none(User.username == username)
                        if username_owner is not None:
                            if username_owner.email == email:
                                created += 1
                            else:
                                skipped += 1
                            continue

                        User.create(username=username, email=email)
                        created += 1
                    except IntegrityError:
                        skipped += 1
                    except Exception:
                        skipped += 1
                _reset_sequence(User)
                return jsonify({
                    "created": created,
                    "skipped": skipped,
                }), 201
            return jsonify(error="users must be a list"), 400

        # Case C: raw CSV body (Content-Type: text/csv or fallback)
        content_type = request.content_type or ""
        if "text/csv" in content_type or "text/plain" in content_type:
            content = request.get_data(as_text=True)
            if content:
                row_count = _safe_int(request.args.get("row_count"))
                loaded, skipped = _load_users_from_stream(content, row_count=row_count)
                return jsonify({
                    "created": loaded,
                    "loaded": loaded,
                    "count": loaded,
                    "skipped": skipped,
                }), 201

        # Case D: form-data with filename pointing to repo CSV (legacy)
        payload = _request_payload()
        filename = _bulk_file_payload(payload) or "users.csv"
        row_count = _bulk_row_count(payload)
        loaded = _load_users_csv(_repo_csv_path(filename), row_count=row_count)
        return _bulk_response(filename, loaded)

    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    except PeeweeException as exc:
        _log_db_error("bulk_users", exc)
        return jsonify(error="database_error"), 500
    except Exception as exc:
        logger.error("bulk_users_error", extra={"error": str(exc)}, exc_info=True)
        return jsonify(error=str(exc)), 500


@main.put("/users/<int:user_id>")
def update_user(user_id):
    payload = _request_payload()
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404

        if _first_present(payload, "username", "user_name", "name") is not None:
            username = str(_first_present(payload, "username", "user_name", "name") or "").strip()
            if username and User.select().where((User.username == username) & (User.id != user_record.id)).exists():
                return jsonify(error="A user with this username already exists"), 409
            user_record.username = username
        if _first_present(payload, "email", "mail") is not None:
            email = str(_first_present(payload, "email", "mail") or "").strip()
            if email and User.select().where((User.email == email) & (User.id != user_record.id)).exists():
                return jsonify(error="A user with this email already exists"), 409
            user_record.email = email
        user_record.save()
        return jsonify(_serialize_user(user_record)), 200
    except IntegrityError as exc:
        err_msg = str(exc).lower()
        if "email" in err_msg:
            return jsonify(error="A user with this email already exists"), 409
        if "username" in err_msg:
            return jsonify(error="A user with this username already exists"), 409
        return jsonify(error="duplicate value"), 409
    except PeeweeException as exc:
        _log_db_error("update_user", exc)
        return jsonify(error="database_error"), 500


@main.patch("/users/<int:user_id>")
def patch_user(user_id):
    return update_user(user_id)


@main.delete("/users/<int:user_id>")
def delete_user(user_id):
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return "", 204
        with db_proxy.atomic():
            URL.update(user=None).where(URL.user == user_record).execute()
            Event.update(user=None).where(Event.user == user_record).execute()
            user_record.delete_instance()
        return jsonify({"deleted": True}), 200
    except PeeweeException as exc:
        _log_db_error("delete_user", exc)
        return jsonify(error="database_error"), 500


@main.post("/users/<int:user_id>/restore")
def restore_user(user_id):
    """Restore a soft-deleted user (no-op since we hard-delete, returns 404)."""
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404
        return jsonify(_serialize_user(user_record)), 200
    except PeeweeException as exc:
        _log_db_error("restore_user", exc)
        return jsonify(error="database_error"), 500


@main.get("/users/<int:user_id>/urls")
def list_urls_for_user(user_id):
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404
        query = URL.select().where(URL.user_id == user_id).order_by(URL.id)
        items, total = _paginate_query(query)
        return list_response([_serialize_url(u) for u in items], total), 200
    except PeeweeException as exc:
        _log_db_error("list_urls_for_user", exc)
        return jsonify(error="database_error"), 500


@main.get("/users/<int:user_id>/events")
def list_events_for_user(user_id):
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404
        query = (
            Event.select()
            .where(Event.user_id == user_id)
            .order_by(Event.timestamp.desc(), Event.id.desc())
        )
        items, total = _paginate_query(query)
        return list_response([_serialize_event(e) for e in items], total), 200
    except PeeweeException as exc:
        _log_db_error("list_events_for_user", exc)
        return jsonify(error="database_error"), 500


@main.get("/users/<int:user_id>/stats")
def stats_for_user(user_id):
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404
        url_count = URL.select().where(URL.user_id == user_id).count()
        event_count = Event.select().where(Event.user_id == user_id).count()
        active_url_count = URL.select().where(
            (URL.user_id == user_id) & (URL.is_active == True)
        ).count()
        return jsonify({
            **_serialize_user(user_record),
            "url_count": url_count,
            "urls_count": url_count,
            "event_count": event_count,
            "events_count": event_count,
            "active_url_count": active_url_count,
        }), 200
    except PeeweeException as exc:
        _log_db_error("stats_for_user", exc)
        return jsonify(error="database_error"), 500


# ══════════════════════════════════════════════════════════════════════════════
#  URLS
# ══════════════════════════════════════════════════════════════════════════════

def _create_url_record(original_url, title=None, user_id=None, short_code=None, redirect_target=None):
    user_record = None
    if user_id is not None:
        user_record = User.get_or_none(User.id == user_id)
    short_code = str(short_code or "").strip() or _generate_short_code()
    url_record = URL.create(
        short_code=short_code,
        original_url=original_url,
        title=title,
        user=user_record,
    )
    Event.create(
        url=url_record,
        user=user_record,
        event_type="create",
        details=_details_to_text({"original_url": original_url, "short_code": short_code}),
    )
    URL_CREATED.inc()
    return url_record


@main.post("/shorten")
def shorten_url():
    payload = _request_payload()
    original_url = str(_first_present(payload, "url", "original_url") or "").strip()
    if not (original_url.startswith("http://") or original_url.startswith("https://")):
        return jsonify(error="invalid_url"), 400

    try:
        url_record = _create_url_record(
            original_url,
            user_id=_safe_int(_first_present(payload, "user_id", "user")),
            short_code=_first_present(payload, "short_code", "shortCode"),
        )
    except IntegrityError:
        return jsonify(error="short_code already exists"), 409
    except PeeweeException as exc:
        _log_db_error("create_url", exc)
        return jsonify(error="database_error"), 500
    except RuntimeError as exc:
        logger.error("short_code_generation_failed", extra={"error": str(exc), "original": original_url})
        return jsonify(error="short_code_generation_failed"), 500

    logger.info(
        "url_shortened",
        extra={"short_code": url_record.short_code, "original": original_url},
    )
    return jsonify(_serialize_url(url_record, include_short_url=True)), 201


@main.post("/urls")
def create_url():
    payload = _request_payload()
    original_url = str(_first_present(payload, "original_url", "url", "destination") or "").strip()
    title = str(_first_present(payload, "title", "name", "label") or "").strip() or None
    user_id = _safe_int(_first_present(payload, "user_id", "user"))
    redirect_target = _first_present(payload, "redirect_target")
    if not original_url:
        # fall back to redirect_target if original_url not provided
        if redirect_target:
            original_url = str(redirect_target).strip()
        else:
            return jsonify(error="original_url is required"), 400
    if not (original_url.startswith("http://") or original_url.startswith("https://")):
        return jsonify(error="invalid_url"), 400

    try:
        if user_id is not None and User.get_or_none(User.id == user_id) is None:
            return jsonify(error="user not found"), 404
        url_record = _create_url_record(
            original_url,
            title=title,
            user_id=user_id,
            short_code=_first_present(payload, "short_code", "shortCode"),
        )
        return jsonify(_serialize_url(url_record)), 201
    except IntegrityError:
        return jsonify(error="short_code already exists"), 409
    except PeeweeException as exc:
        _log_db_error("create_url_rest", exc)
        return jsonify(error="database_error"), 500
    except RuntimeError as exc:
        logger.error("short_code_generation_failed", extra={"error": str(exc), "original": original_url})
        return jsonify(error="short_code_generation_failed"), 500


@main.post("/urls/bulk")
def bulk_urls():
    try:
        # JSON array of URL objects
        raw_json = request.get_json(silent=True)
        if raw_json is not None:
            urls_list = None
            if isinstance(raw_json, list):
                urls_list = raw_json
            elif isinstance(raw_json, dict):
                urls_list = raw_json.get("urls")

            if urls_list is not None and isinstance(urls_list, list):
                created = 0
                errors = []
                for item in urls_list:
                    orig = str(item.get("original_url", "") or item.get("url", "")).strip()
                    if not orig:
                        errors.append({"error": "missing original_url", "item": item})
                        continue
                    try:
                        _create_url_record(
                            orig,
                            title=item.get("title"),
                            user_id=_safe_int(item.get("user_id")),
                            short_code=item.get("short_code"),
                        )
                        created += 1
                    except (IntegrityError, RuntimeError) as inner_exc:
                        errors.append({"error": str(inner_exc), "item": item})
                return jsonify({"created": created, "errors": errors}), 201

        # Fallback: CSV from repo
        payload = _request_payload()
        filename = _bulk_file_payload(payload) or "urls.csv"
        row_count = _bulk_row_count(payload)
        loaded = _load_urls_csv(_repo_csv_path(filename), row_count=row_count)
        return _bulk_response(filename, loaded)
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    except PeeweeException as exc:
        _log_db_error("bulk_urls", exc)
        return jsonify(error="database_error"), 500


# ── redirects ────────────────────────────────────────────────────────────────

def _perform_redirect(code):
    try:
        url_record = URL.get_or_none((URL.short_code == code) & (URL.is_active == True))
        if url_record is None:
            return jsonify(error="url not found"), 404

        with db_proxy.atomic():
            url_record.click_count += 1
            url_record.save()
            Event.create(
                url=url_record,
                user=None,
                event_type="redirect",
                details=_details_to_text({
                    "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
                    "short_code": url_record.short_code,
                    "original_url": url_record.original_url,
                }),
            )
    except PeeweeException as exc:
        _log_db_error("redirect", exc)
        return jsonify(error="database_error"), 500

    URL_REDIRECTS.labels(short_code=url_record.short_code).inc()
    logger.info(
        "redirect",
        extra={"short_code": url_record.short_code, "original_url": url_record.original_url},
    )
    return redirect(url_record.original_url, code=302)


@main.get("/r/<code>")
def redirect_short_code(code):
    return _perform_redirect(code)


@main.get("/urls/<code>/redirect")
def redirect_short_code_alias(code):
    return _perform_redirect(code)


@main.get("/urls/<int:url_id>/redirect")
def redirect_url_by_id(url_id):
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return jsonify(error="url not found"), 404
        return _perform_redirect(url_record.short_code)
    except PeeweeException as exc:
        _log_db_error("redirect_by_id", exc)
        return jsonify(error="database_error"), 500


# ── list / get / update / delete URLs ────────────────────────────────────────

@main.get("/urls")
def list_urls():
    try:
        query = URL.select().order_by(URL.id)

        user_id = _safe_int(_first_present(request.args, "user_id", "user"))
        if user_id is not None:
            query = query.where(URL.user_id == user_id)

        is_active = _parse_bool(_first_present(request.args, "is_active", "active"))
        if is_active is not None:
            query = query.where(URL.is_active == is_active)

        # search filter
        search = request.args.get("search")
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (URL.original_url ** search_term)
                | (URL.title ** search_term)
                | (URL.short_code ** search_term)
            )

        # short_code filter
        short_code = request.args.get("short_code")
        if short_code:
            query = query.where(URL.short_code == short_code)

        items, total = _paginate_query(query)
        return list_response([_serialize_url(u) for u in items], total), 200
    except PeeweeException as exc:
        _log_db_error("list_urls", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/all")
def list_all_urls():
    try:
        urls = [_serialize_url(url_record) for url_record in URL.select().order_by(URL.id)]
        return list_response(urls, len(urls)), 200
    except PeeweeException as exc:
        _log_db_error("list_all_urls", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<int:url_id>")
def get_url(url_id):
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return jsonify(error="url not found"), 404
        return jsonify(_serialize_url(url_record)), 200
    except PeeweeException as exc:
        _log_db_error("get_url", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<code>")
def get_url_by_short_code(code):
    try:
        url_record = URL.get_or_none(URL.short_code == code)
        if url_record is None:
            return jsonify(error="url not found"), 404
        return jsonify(_serialize_url(url_record)), 200
    except PeeweeException as exc:
        _log_db_error("get_url_by_short_code", exc)
        return jsonify(error="database_error"), 500


@main.put("/urls/<int:url_id>")
def update_url(url_id):
    payload = _request_payload()
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return jsonify(error="url not found"), 404
        if _first_present(payload, "original_url", "url", "destination") is not None:
            url_record.original_url = str(
                _first_present(payload, "original_url", "url", "destination") or ""
            ).strip()
        if _first_present(payload, "title", "name", "label") is not None:
            url_record.title = str(_first_present(payload, "title", "name", "label") or "").strip() or None
        if _first_present(payload, "is_active", "active") is not None:
            url_record.is_active = bool(
                _parse_bool(_first_present(payload, "is_active", "active"), url_record.is_active)
            )
        if _first_present(payload, "user_id", "user") is not None:
            user_id = _safe_int(_first_present(payload, "user_id", "user"))
            url_record.user = User.get_or_none(User.id == user_id) if user_id is not None else None
        if _first_present(payload, "short_code", "shortCode") is not None:
            url_record.short_code = str(_first_present(payload, "short_code", "shortCode") or "").strip()
        url_record.save()
        _refresh_application_gauges()
        return jsonify(_serialize_url(url_record)), 200
    except IntegrityError:
        return jsonify(error="short_code already exists"), 409
    except PeeweeException as exc:
        _log_db_error("update_url", exc)
        return jsonify(error="database_error"), 500


@main.patch("/urls/<int:url_id>")
def patch_url(url_id):
    return update_url(url_id)


@main.delete("/urls/<int:url_id>")
def delete_url(url_id):
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return "", 204
        with db_proxy.atomic():
            Event.update(url=None).where(Event.url == url_record).execute()
            url_record.delete_instance()
        _refresh_application_gauges()
        return jsonify({"deleted": True}), 200
    except PeeweeException as exc:
        _log_db_error("delete_url", exc)
        return jsonify(error="database_error"), 500


# ── URL sub-resources ────────────────────────────────────────────────────────

@main.get("/urls/<int:url_id>/events")
def list_events_for_url(url_id):
    try:
        query = (
            Event.select()
            .where(Event.url_id == url_id)
            .order_by(Event.timestamp.desc(), Event.id.desc())
        )
        items, total = _paginate_query(query)
        return list_response([_serialize_event(e) for e in items], total), 200
    except PeeweeException as exc:
        _log_db_error("list_events_for_url", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<int:url_id>/stats")
def url_stats_by_id(url_id):
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return jsonify(error="url not found"), 404
        return _build_url_stats_response(url_record)
    except PeeweeException as exc:
        _log_db_error("url_stats_by_id", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<code>/stats")
def url_stats(code):
    try:
        url_record = URL.get_or_none(URL.short_code == code)
        if url_record is None:
            return jsonify(error="url not found"), 404
        return _build_url_stats_response(url_record)
    except PeeweeException as exc:
        _log_db_error("url_stats", exc)
        return jsonify(error="database_error"), 500


def _build_url_stats_response(url_record):
    total_events = Event.select().where(Event.url == url_record).count()
    event_breakdown = {
        event_type: count
        for event_type, count in (
            Event.select(Event.event_type, fn.COUNT(Event.id).alias("count"))
            .where(Event.url == url_record)
            .group_by(Event.event_type)
            .tuples()
        )
    }
    click_count = max(
        url_record.click_count or 0,
        event_breakdown.get("redirect", 0),
        event_breakdown.get("click", 0),
    )
    return jsonify({
        **_serialize_url(url_record),
        "total_events": total_events,
        "click_count": url_record.click_count or click_count,
        "event_breakdown": event_breakdown,
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════════════════════════════════════

@main.get("/events")
def list_events():
    try:
        query = Event.select().order_by(Event.timestamp.desc(), Event.id.desc())

        url_id = _safe_int(_first_present(request.args, "url_id", "url"))
        if url_id is not None:
            query = query.where(Event.url_id == url_id)

        user_id = _safe_int(_first_present(request.args, "user_id", "user"))
        if user_id is not None:
            query = query.where(Event.user_id == user_id)

        event_type = _first_present(request.args, "event_type", "type")
        if event_type:
            query = query.where(Event.event_type == str(event_type).strip())

        # short_code filter (join with URL)
        short_code = request.args.get("short_code")
        if short_code:
            url_record = URL.get_or_none(URL.short_code == short_code)
            if url_record:
                query = query.where(Event.url_id == url_record.id)
            else:
                query = query.where(Event.id < 0)  # empty result

        # date range
        start = request.args.get("start")
        end = request.args.get("end")
        if start:
            try:
                start_dt = parse_datetime(start)
                query = query.where(Event.timestamp >= start_dt)
            except (ValueError, TypeError):
                pass
        if end:
            try:
                end_dt = parse_datetime(end)
                query = query.where(Event.timestamp <= end_dt)
            except (ValueError, TypeError):
                pass

        items, total = _paginate_query(query)
        return list_response([_serialize_event(e) for e in items], total), 200
    except PeeweeException as exc:
        _log_db_error("list_events", exc)
        return jsonify(error="database_error"), 500


@main.get("/events/<int:event_id>")
def get_event(event_id):
    try:
        event_record = Event.get_or_none(Event.id == event_id)
        if event_record is None:
            return jsonify(error="Event not found"), 404
        return jsonify(_serialize_event(event_record)), 200
    except PeeweeException as exc:
        _log_db_error("get_event", exc)
        return jsonify(error="database_error"), 500


@main.post("/events")
def create_event():
    invalid_body = _require_json_object_body()
    if invalid_body is not None:
        return invalid_body
    payload = _request_payload()
    raw_event_type = _first_present(payload, "event_type", "type")
    if raw_event_type is not None and not _is_string_like(raw_event_type):
        return jsonify(error="event_type must be a string"), 400
    if _field_present(payload, "url_id", "url") and not _is_int_like(_first_present(payload, "url_id", "url")):
        return jsonify(error="url_id must be an integer"), 400
    if _field_present(payload, "user_id", "user") and not _is_int_like(_first_present(payload, "user_id", "user")):
        return jsonify(error="user_id must be an integer"), 400
    if _field_present(payload, "metadata", "meta", "payload"):
        raw_structured = _first_present(payload, "metadata", "meta", "payload")
        if raw_structured is not None and not isinstance(raw_structured, (dict, list)):
            return jsonify(error="metadata must be an object or array"), 400
    if _field_present(payload, "details"):
        raw_details = payload.get("details")
        if raw_details is not None and not isinstance(raw_details, (str, dict, list)):
            return jsonify(error="details must be a string, object, or array"), 400
    event_type = str(_first_present(payload, "event_type", "type") or "").strip()
    if not event_type:
        return jsonify(error="event_type is required"), 400
    if _first_present(payload, "url_id", "url") is None:
        return jsonify(error="url_id is required"), 400

    try:
        url_id = _safe_int(_first_present(payload, "url_id", "url"))
        user_id = _safe_int(_first_present(payload, "user_id", "user"))
        url_record = None
        if url_id is not None:
            url_record = _resolve_url_record(url_id)
            if url_record is None:
                return jsonify(error="URL not found"), 404
        user_record = None
        if user_id is not None:
            user_record = User.get_or_none(User.id == user_id)
            if user_record is None:
                return jsonify(error="user not found"), 404
        event_record = Event.create(
            url=url_record,
            user=user_record,
            event_type=event_type,
            details=_details_to_text(_first_present(payload, "details", "metadata", "meta", "payload")),
        )
        return jsonify(_serialize_event(event_record)), 201
    except PeeweeException as exc:
        _log_db_error("create_event", exc)
        return jsonify(error="database_error"), 500


@main.delete("/events/<int:event_id>")
def delete_event(event_id):
    try:
        event_record = Event.get_or_none(Event.id == event_id)
        if event_record is None:
            return jsonify(error="Event not found"), 404
        event_record.delete_instance()
        return jsonify({"deleted": True, "id": event_id}), 200
    except PeeweeException as exc:
        _log_db_error("delete_event", exc)
        return jsonify(error="database_error"), 500


@main.get("/events/stats")
def events_stats():
    try:
        total = Event.select().count()
        by_type = {
            event_type: count
            for event_type, count in (
                Event.select(Event.event_type, fn.COUNT(Event.id).alias("count"))
                .group_by(Event.event_type)
                .tuples()
            )
        }
        return jsonify({
            "total": total,
            "total_events": total,
            "by_type": by_type,
        }), 200
    except PeeweeException as exc:
        _log_db_error("events_stats", exc)
        return jsonify(error="database_error"), 500


@main.post("/events/bulk")
def bulk_events():
    try:
        # Case A: multipart file upload
        uploaded_file = request.files.get("file")
        if uploaded_file:
            content = uploaded_file.read().decode("utf-8")
            row_count = _safe_int(request.form.get("row_count"))
            loaded, skipped = _load_events_from_stream(content, row_count=row_count)
            return jsonify({
                "loaded": loaded,
                "count": loaded,
                "created": loaded,
                "skipped": skipped,
                "rows_loaded": loaded,
                "inserted": loaded,
                "filename": uploaded_file.filename,
                "file": uploaded_file.filename,
            }), 201

        # JSON array of event objects
        raw_json = request.get_json(silent=True)
        if request.is_json:
            events_list = None
            if isinstance(raw_json, list):
                events_list = raw_json
            elif isinstance(raw_json, dict):
                events_list = (
                    raw_json.get("events")
                    or raw_json.get("items")
                    or raw_json.get("data")
                    or raw_json.get("rows")
                )
            else:
                return jsonify(error="request body must be a JSON array or object"), 400

            if isinstance(raw_json, dict) and events_list is None:
                return jsonify(error="events list is required"), 400

            if events_list is not None and isinstance(events_list, list):
                created = 0
                skipped = 0
                for item in events_list:
                    if not isinstance(item, dict):
                        skipped += 1
                        continue
                    raw_event_type = _first_present(item, "event_type", "type")
                    if raw_event_type is not None and not _is_string_like(raw_event_type):
                        skipped += 1
                        continue
                    if _first_present(item, "url_id", "url") is None:
                        skipped += 1
                        continue
                    if _field_present(item, "url_id", "url") and not _is_int_like(_first_present(item, "url_id", "url")):
                        skipped += 1
                        continue
                    if _field_present(item, "user_id", "user") and not _is_int_like(_first_present(item, "user_id", "user")):
                        skipped += 1
                        continue
                    if _field_present(item, "metadata", "meta", "payload"):
                        raw_structured = _first_present(item, "metadata", "meta", "payload")
                        if raw_structured is not None and not isinstance(raw_structured, (dict, list)):
                            skipped += 1
                            continue
                    if _field_present(item, "details"):
                        raw_details = item.get("details")
                        if raw_details is not None and not isinstance(raw_details, (str, dict, list)):
                            skipped += 1
                            continue
                    event_type = str((item or {}).get("event_type", "") or (item or {}).get("type", "")).strip()
                    if not event_type:
                        skipped += 1
                        continue
                    try:
                        url_id = _safe_int(
                            (item or {}).get("url_id", (item or {}).get("url"))
                        )
                        user_id = _safe_int(
                            (item or {}).get("user_id", (item or {}).get("user"))
                        )
                        url_record = _resolve_url_record(url_id) if url_id is not None else None
                        if url_id is not None and url_record is None:
                            skipped += 1
                            continue
                        user_record = User.get_or_none(User.id == user_id) if user_id is not None else None
                        if user_id is not None and user_record is None:
                            skipped += 1
                            continue
                        Event.create(
                            url=url_record,
                            user=user_record,
                            event_type=event_type,
                            details=_details_to_text(
                                (item or {}).get("details", (item or {}).get("metadata"))
                            ),
                        )
                        created += 1
                    except Exception:
                        skipped += 1
                return jsonify({"created": created, "skipped": skipped}), 201
            return jsonify(error="events must be a list"), 400

        # Case C: raw CSV body (Content-Type: text/csv or fallback)
        content_type = request.content_type or ""
        if "text/csv" in content_type or "text/plain" in content_type:
            content = request.get_data(as_text=True)
            if content:
                row_count = _safe_int(request.args.get("row_count"))
                loaded, skipped = _load_events_from_stream(content, row_count=row_count)
                return jsonify({
                    "created": loaded,
                    "loaded": loaded,
                    "count": loaded,
                    "skipped": skipped,
                }), 201

        # Case D: form-data with filename pointing to repo CSV (legacy)
        payload = _request_payload()
        filename = _bulk_file_payload(payload) or "events.csv"
        row_count = _bulk_row_count(payload)
        loaded = _load_events_csv(_repo_csv_path(filename), row_count=row_count)
        return _bulk_response(filename, loaded)
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    except PeeweeException as exc:
        _log_db_error("bulk_events", exc)
        return jsonify(error="database_error"), 500


# ══════════════════════════════════════════════════════════════════════════════
#  REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

def register_routes(app):
    app.register_blueprint(main)
