import logging
import time
import traceback

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from app.database import db_proxy, initialize_db
from app.logger import setup_logging
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY
from app.routes import ensure_sample_data, register_routes


def create_app():
    setup_logging()
    load_dotenv()

    logger = logging.getLogger(__name__)
    app = Flask(__name__)

    @app.before_request
    def _before_request():
        g.start_time = time.perf_counter()
        if request.endpoint == "main.metrics":
            return
        try:
            db_proxy.connect(reuse_if_open=True)
        except Exception:
            pass

    # ── error handlers ───────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "method not allowed"}), 405

    @app.errorhandler(Exception)
    def global_error_handler(e):
        if isinstance(e, HTTPException):
            return jsonify({"error": e.description or e.name}), e.code
        logger.error(
            "unhandled_exception",
            extra={"error": str(e), "type": type(e).__name__, "tb": traceback.format_exc()},
        )
        return jsonify({"error": str(e)}), 500

    @app.teardown_appcontext
    def _teardown_db(exc):
        if not db_proxy.is_closed():
            db_proxy.close()

    @app.after_request
    def _after_request(response):
        endpoint = request.endpoint or request.path or "unknown"
        status = str(response.status_code)
        start_time = getattr(g, "start_time", None)
        duration = time.perf_counter() - start_time if start_time is not None else 0.0

        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status=status,
        ).inc()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration)

        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 2),
                "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
            },
        )

        return response

    initialize_db(app)
    ensure_sample_data()
    register_routes(app)
    logger.info("app_started")

    return app
