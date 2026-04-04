import json
import logging
import secrets
import string

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from peewee import PeeweeException, fn
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.database import db_proxy
from app.logger import get_recent_logs
from app.metrics import ACTIVE_URLS_TOTAL, DB_ERRORS, URL_CREATED, URL_REDIRECTS
from app.metrics import refresh_system_metrics
from app.models import Event, URL

logger = logging.getLogger(__name__)
main = Blueprint("main", __name__)

SHORT_CODE_ALPHABET = string.ascii_letters + string.digits
SHORT_CODE_LENGTH = 6
SHORT_CODE_MAX_ATTEMPTS = 64


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


def _serialize_url_list_item(url_record):
    return {
        "short_code": url_record.short_code,
        "original_url": url_record.original_url,
        "click_count": url_record.click_count,
        "is_active": url_record.is_active,
        "short_url": url_for("main.redirect_short_code", code=url_record.short_code, _external=True),
        "created_at": url_record.created_at.isoformat(),
    }


def _refresh_application_gauges():
    try:
        ACTIVE_URLS_TOTAL.set(URL.select().where(URL.is_active == True).count())
    except PeeweeException as exc:
        _log_db_error("active_urls_metric", exc)


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
                "urls": "/urls",
                "all_urls": "/urls/all",
                "logs": "/logs/recent",
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


@main.post("/shorten")
def shorten_url():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}

    original_url = str(payload.get("url", "")).strip()
    if not (
        original_url.startswith("http://") or original_url.startswith("https://")
    ):
        return jsonify(error="invalid_url"), 400

    try:
        with db_proxy.atomic():
            short_code = _generate_short_code()
            url_record = URL.create(short_code=short_code, original_url=original_url)
            Event.create(
                url=url_record,
                event_type="created",
                details=json.dumps({"original_url": original_url}),
            )
    except PeeweeException as exc:
        _log_db_error("create_url", exc)
        return jsonify(error="database_error"), 500
    except RuntimeError as exc:
        logger.error(
            "short_code_generation_failed",
            extra={"error": str(exc), "original": original_url},
        )
        return jsonify(error="short_code_generation_failed"), 500

    URL_CREATED.inc()
    logger.info(
        "url_shortened",
        extra={"short_code": short_code, "original": original_url},
    )

    return (
        jsonify(
            short_code=short_code,
            short_url=url_for("main.redirect_short_code", code=short_code, _external=True),
            original_url=original_url,
        ),
        201,
    )


@main.get("/r/<code>")
def redirect_short_code(code):
    try:
        url_record = URL.get_or_none(URL.short_code == code)
        if url_record is None:
            return jsonify(error="not_found"), 404

        with db_proxy.atomic():
            url_record.click_count += 1
            url_record.save()
            Event.create(
                url=url_record,
                event_type="redirect",
                details=json.dumps({"ip": request.headers.get("X-Forwarded-For", request.remote_addr)}),
            )
    except PeeweeException as exc:
        _log_db_error("redirect", exc)
        return jsonify(error="database_error"), 500

    URL_REDIRECTS.labels(short_code=url_record.short_code).inc()
    logger.info(
        "redirect",
        extra={
            "short_code": url_record.short_code,
            "original_url": url_record.original_url,
        },
    )

    return redirect(url_record.original_url, code=302)


@main.get("/urls")
def list_urls():
    try:
        urls = [
            _serialize_url_list_item(url_record)
            for url_record in (
                URL.select()
                .where(URL.is_active == True)
                .order_by(URL.created_at.desc())
                .limit(50)
            )
        ]
    except PeeweeException as exc:
        _log_db_error("list_urls", exc)
        return jsonify(error="database_error"), 500

    return jsonify(urls)


@main.get("/urls/all")
def list_all_urls():
    try:
        urls = [
            _serialize_url_list_item(url_record)
            for url_record in URL.select().order_by(URL.created_at.desc())
        ]
    except PeeweeException as exc:
        _log_db_error("list_all_urls", exc)
        return jsonify(error="database_error"), 500

    return jsonify(urls)


@main.get("/urls/<code>/stats")
def url_stats(code):
    try:
        url_record = URL.get_or_none(URL.short_code == code)
        if url_record is None:
            return jsonify(error="not_found"), 404

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
    except PeeweeException as exc:
        _log_db_error("url_stats", exc)
        return jsonify(error="database_error"), 500

    return jsonify(
        {
            "short_code": url_record.short_code,
            "title": url_record.title,
            "original_url": url_record.original_url,
            "click_count": url_record.click_count,
            "is_active": url_record.is_active,
            "created_at": url_record.created_at.isoformat(),
            "updated_at": url_record.updated_at.isoformat(),
            "total_events": total_events,
            "event_breakdown": event_breakdown,
        }
    )


def register_routes(app):
    app.register_blueprint(main)
