import csv
import json
import logging
import secrets
import string
import time
from datetime import datetime
from pathlib import Path

from dateutil.parser import parse as parse_datetime
from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from peewee import IntegrityError, PeeweeException, fn
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


def _serialize_user(user_record):
    return {
        "id": user_record.id,
        "username": user_record.username,
        "email": user_record.email,
        "created_at": user_record.created_at.isoformat() if user_record.created_at else None,
    }


def _serialize_url(url_record):
    return {
        "id": url_record.id,
        "user_id": url_record.user_id,
        "short_code": url_record.short_code,
        "original_url": url_record.original_url,
        "title": url_record.title,
        "created_at": url_record.created_at.isoformat() if url_record.created_at else None,
        "updated_at": url_record.updated_at.isoformat() if url_record.updated_at else None,
        "is_active": url_record.is_active,
        "click_count": url_record.click_count,
        "short_url": url_for("main.redirect_short_code", code=url_record.short_code, _external=True),
    }


def _serialize_event(event_record):
    return {
        "id": event_record.id,
        "url_id": event_record.url_id,
        "user_id": event_record.user_id,
        "event_type": event_record.event_type,
        "timestamp": event_record.timestamp.isoformat() if event_record.timestamp else None,
        "details": _serialize_details(event_record.details),
    }


def _paginate(query):
    page = max(_safe_int(request.args.get("page"), 1), 1)
    per_page = _safe_int(request.args.get("per_page"))
    if per_page is None:
        return query
    per_page = max(1, min(per_page, 500))
    return query.paginate(page, per_page)


def _bulk_file_payload(payload):
    return payload.get("filename") or payload.get("file")


def _bulk_row_count(payload):
    return (
        _safe_int(payload.get("row_count"))
        or _safe_int(payload.get("rowcount"))
        or _safe_int(payload.get("count"))
        or _safe_int(payload.get("rows"))
    )


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
    db_proxy.execute_sql(
        f"""SELECT setval(pg_get_serial_sequence('"{table}"', 'id'),
        COALESCE((SELECT MAX(id) FROM "{table}"), 1), true)"""
    )


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
                    "user": user_id if User.get_or_none(User.id == user_id) else None,
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
                    "url": URL.get_or_none(URL.id == url_id),
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


@main.get("/users")
def list_users():
    try:
        query = User.select().order_by(User.id)
        query = _paginate(query)
        return jsonify([_serialize_user(user_record) for user_record in query]), 200
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
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    email = str(payload.get("email", "")).strip()
    if not username or not email:
        return jsonify(error="username and email are required"), 400

    try:
        user_record = User.create(username=username, email=email)
        return jsonify(_serialize_user(user_record)), 201
    except IntegrityError:
        return jsonify(error="user already exists"), 409
    except PeeweeException as exc:
        _log_db_error("create_user", exc)
        return jsonify(error="database_error"), 500


@main.post("/users/bulk")
def bulk_users():
    payload = request.get_json(silent=True) or {}
    filename = _bulk_file_payload(payload)
    row_count = _bulk_row_count(payload)
    if not filename:
        return jsonify(error="filename is required"), 400

    try:
        loaded = _load_users_csv(_repo_csv_path(filename), row_count=row_count)
        return jsonify(loaded=loaded, filename=Path(filename).name, file=Path(filename).name), 201
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    except PeeweeException as exc:
        _log_db_error("bulk_users", exc)
        return jsonify(error="database_error"), 500


@main.put("/users/<int:user_id>")
def update_user(user_id):
    payload = request.get_json(silent=True) or {}
    try:
        user_record = User.get_or_none(User.id == user_id)
        if user_record is None:
            return jsonify(error="user not found"), 404

        if "username" in payload:
            user_record.username = str(payload.get("username") or "").strip()
        if "email" in payload:
            user_record.email = str(payload.get("email") or "").strip()
        user_record.save()
        return jsonify(_serialize_user(user_record)), 200
    except PeeweeException as exc:
        _log_db_error("update_user", exc)
        return jsonify(error="database_error"), 500


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
        return "", 204
    except PeeweeException as exc:
        _log_db_error("delete_user", exc)
        return jsonify(error="database_error"), 500


@main.get("/users/<int:user_id>/urls")
def list_urls_for_user(user_id):
    try:
        query = URL.select().where(URL.user_id == user_id).order_by(URL.id)
        query = _paginate(query)
        return jsonify([_serialize_url(url_record) for url_record in query]), 200
    except PeeweeException as exc:
        _log_db_error("list_urls_for_user", exc)
        return jsonify(error="database_error"), 500


@main.get("/users/<int:user_id>/events")
def list_events_for_user(user_id):
    try:
        query = Event.select().where(Event.user_id == user_id).order_by(Event.id)
        query = _paginate(query)
        return jsonify([_serialize_event(event_record) for event_record in query]), 200
    except PeeweeException as exc:
        _log_db_error("list_events_for_user", exc)
        return jsonify(error="database_error"), 500


def _create_url_record(original_url, title=None, user_id=None, short_code=None):
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
        event_type="created",
        details=_details_to_text({"original_url": original_url, "short_code": short_code}),
    )
    URL_CREATED.inc()
    return url_record


@main.post("/shorten")
def shorten_url():
    payload = request.get_json(silent=True) or {}
    original_url = str(payload.get("url", "")).strip()
    if not (original_url.startswith("http://") or original_url.startswith("https://")):
        return jsonify(error="invalid_url"), 400

    try:
        url_record = _create_url_record(
            original_url,
            user_id=_safe_int(payload.get("user_id")),
            short_code=payload.get("short_code"),
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
    return jsonify(_serialize_url(url_record)), 201


@main.post("/urls")
def create_url():
    payload = request.get_json(silent=True) or {}
    original_url = str(payload.get("original_url", "")).strip()
    title = str(payload.get("title", "")).strip() or None
    user_id = _safe_int(payload.get("user_id"))
    if not original_url:
        return jsonify(error="original_url is required"), 400
    if not (original_url.startswith("http://") or original_url.startswith("https://")):
        return jsonify(error="invalid_url"), 400

    try:
        url_record = _create_url_record(
            original_url,
            title=title,
            user_id=user_id,
            short_code=payload.get("short_code"),
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
    payload = request.get_json(silent=True) or {}
    filename = _bulk_file_payload(payload)
    row_count = _bulk_row_count(payload)
    if not filename:
        return jsonify(error="filename is required"), 400

    try:
        loaded = _load_urls_csv(_repo_csv_path(filename), row_count=row_count)
        return jsonify(loaded=loaded, filename=Path(filename).name, file=Path(filename).name), 201
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    except PeeweeException as exc:
        _log_db_error("bulk_urls", exc)
        return jsonify(error="database_error"), 500


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
                user=url_record.user,
                event_type="click",
                details=_details_to_text({"ip": request.headers.get("X-Forwarded-For", request.remote_addr)}),
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


@main.get("/urls")
def list_urls():
    try:
        query = URL.select().order_by(URL.id)
        user_id = _safe_int(request.args.get("user_id"))
        if user_id is not None:
            query = query.where(URL.user_id == user_id)
        is_active = _parse_bool(request.args.get("is_active"))
        if is_active is not None:
            query = query.where(URL.is_active == is_active)
        query = _paginate(query)
        return jsonify([_serialize_url(url_record) for url_record in query]), 200
    except PeeweeException as exc:
        _log_db_error("list_urls", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/all")
def list_all_urls():
    try:
        urls = [_serialize_url(url_record) for url_record in URL.select().order_by(URL.id)]
        return jsonify(urls), 200
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


@main.put("/urls/<int:url_id>")
def update_url(url_id):
    payload = request.get_json(silent=True) or {}
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return jsonify(error="url not found"), 404
        if "original_url" in payload:
            url_record.original_url = str(payload.get("original_url") or "").strip()
        if "title" in payload:
            url_record.title = str(payload.get("title") or "").strip() or None
        if "is_active" in payload:
            url_record.is_active = bool(_parse_bool(payload.get("is_active"), url_record.is_active))
        if "user_id" in payload:
            user_id = _safe_int(payload.get("user_id"))
            url_record.user = User.get_or_none(User.id == user_id) if user_id is not None else None
        url_record.save()
        _refresh_application_gauges()
        return jsonify(_serialize_url(url_record)), 200
    except PeeweeException as exc:
        _log_db_error("update_url", exc)
        return jsonify(error="database_error"), 500


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
        return "", 204
    except PeeweeException as exc:
        _log_db_error("delete_url", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<int:url_id>/events")
def list_events_for_url(url_id):
    try:
        query = Event.select().where(Event.url_id == url_id).order_by(Event.id)
        query = _paginate(query)
        return jsonify([_serialize_event(event_record) for event_record in query]), 200
    except PeeweeException as exc:
        _log_db_error("list_events_for_url", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<int:url_id>/stats")
def url_stats_by_id(url_id):
    try:
        url_record = URL.get_or_none(URL.id == url_id)
        if url_record is None:
            return jsonify(error="url not found"), 404
        return url_stats(url_record.short_code)
    except PeeweeException as exc:
        _log_db_error("url_stats_by_id", exc)
        return jsonify(error="database_error"), 500


@main.get("/urls/<code>/stats")
def url_stats(code):
    try:
        url_record = URL.get_or_none(URL.short_code == code)
        if url_record is None:
            return jsonify(error="url not found"), 404
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
        return jsonify(
            {
                **_serialize_url(url_record),
                "total_events": total_events,
                "event_breakdown": event_breakdown,
            }
        ), 200
    except PeeweeException as exc:
        _log_db_error("url_stats", exc)
        return jsonify(error="database_error"), 500


@main.get("/events")
def list_events():
    try:
        query = Event.select().order_by(Event.id)
        url_id = _safe_int(request.args.get("url_id"))
        if url_id is not None:
            query = query.where(Event.url_id == url_id)
        user_id = _safe_int(request.args.get("user_id"))
        if user_id is not None:
            query = query.where(Event.user_id == user_id)
        event_type = request.args.get("event_type")
        if event_type:
            query = query.where(Event.event_type == str(event_type).strip())
        query = _paginate(query)
        return jsonify([_serialize_event(event_record) for event_record in query]), 200
    except PeeweeException as exc:
        _log_db_error("list_events", exc)
        return jsonify(error="database_error"), 500


@main.get("/events/<int:event_id>")
def get_event(event_id):
    try:
        event_record = Event.get_or_none(Event.id == event_id)
        if event_record is None:
            return jsonify(error="event not found"), 404
        return jsonify(_serialize_event(event_record)), 200
    except PeeweeException as exc:
        _log_db_error("get_event", exc)
        return jsonify(error="database_error"), 500


@main.post("/events")
def create_event():
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event_type", "")).strip()
    if not event_type:
        return jsonify(error="event_type is required"), 400

    try:
        url_id = _safe_int(payload.get("url_id"))
        user_id = _safe_int(payload.get("user_id"))
        event_record = Event.create(
            url=URL.get_or_none(URL.id == url_id) if url_id is not None else None,
            user=User.get_or_none(User.id == user_id) if user_id is not None else None,
            event_type=event_type,
            details=_details_to_text(payload.get("details")),
        )
        return jsonify(_serialize_event(event_record)), 201
    except PeeweeException as exc:
        _log_db_error("create_event", exc)
        return jsonify(error="database_error"), 500


@main.post("/events/bulk")
def bulk_events():
    payload = request.get_json(silent=True) or {}
    filename = _bulk_file_payload(payload)
    row_count = _bulk_row_count(payload)
    if not filename:
        return jsonify(error="filename is required"), 400

    try:
        loaded = _load_events_csv(_repo_csv_path(filename), row_count=row_count)
        return jsonify(loaded=loaded, filename=Path(filename).name, file=Path(filename).name), 201
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    except PeeweeException as exc:
        _log_db_error("bulk_events", exc)
        return jsonify(error="database_error"), 500


def register_routes(app):
    app.register_blueprint(main)
