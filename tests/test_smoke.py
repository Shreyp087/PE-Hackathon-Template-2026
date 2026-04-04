import json

from flask import Flask

from app.logger import CustomJsonFormatter
import app.routes as route_module
from app.routes import register_routes


def make_test_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_routes(app)
    return app


def test_health_route():
    app = make_test_app()
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_metrics_route_exposes_prometheus_output(monkeypatch):
    app = make_test_app()
    client = app.test_client()
    monkeypatch.setattr(route_module, "_refresh_application_gauges", lambda: None)

    response = client.get("/metrics")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "text/plain" in response.content_type
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "url_created_total" in body


def test_system_route_returns_expected_keys():
    app = make_test_app()
    client = app.test_client()

    response = client.get("/system")
    payload = response.get_json()

    assert response.status_code == 200
    assert {
        "cpu_percent",
        "memory_total_mb",
        "memory_used_mb",
        "memory_percent",
        "disk_percent",
    }.issubset(payload.keys())


def test_shorten_rejects_invalid_url_before_db_work():
    app = make_test_app()
    client = app.test_client()

    response = client.post("/shorten", json={"url": "ftp://example.com"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_url"}


def test_json_formatter_adds_required_fields():
    formatter = CustomJsonFormatter()
    record = __import__("logging").LogRecord(
        name="app.routes",
        level=20,
        pathname=__file__,
        lineno=1,
        msg="redirect",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "redirect"
    assert payload["level"] == "INFO"
    assert payload["component"] == "app.routes"
    assert "timestamp" in payload
