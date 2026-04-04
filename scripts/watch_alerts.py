import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


HEADER_LINE = "════════════════════════════════════════════"
REQUEST_TIMEOUT_SECONDS = 10


def parse_args():
    parser = argparse.ArgumentParser(
        description="Watch Prometheus and Alertmanager for live golden-signal status."
    )
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--alertmanager", default="http://localhost:9093")
    parser.add_argument("--interval", type=int, default=10)
    return parser.parse_args()


def fetch_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def prometheus_query(base_url, query):
    query_string = urllib.parse.urlencode({"query": query})
    payload = fetch_json(base_url.rstrip("/") + "/api/v1/query?" + query_string)
    if not payload or payload.get("status") != "success":
        return []

    data = payload.get("data", {})
    result_type = data.get("resultType")
    result = data.get("result", [])

    if result_type == "scalar" and isinstance(result, list) and len(result) == 2:
        try:
            return [float(result[1])]
        except (TypeError, ValueError):
            return []

    values = []
    for item in result:
        try:
            values.append(float(item["value"][1]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return values


def alertmanager_active_alerts(base_url):
    url = (
        base_url.rstrip("/")
        + "/api/v2/alerts?active=true&silenced=false"
    )
    payload = fetch_json(url)
    if isinstance(payload, list):
        return payload
    return []


def sum_values(values):
    return sum(values) if values else 0.0


def single_value(values):
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return max(values)


def format_total(value):
    return format(int(round(value)), ",")


def format_duration(starts_at):
    if not starts_at:
        return "unknown"

    try:
        started = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"

    now = datetime.now(timezone.utc)
    elapsed = max(0, int((now - started).total_seconds()))
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def print_block(poll_number, metrics, alerts):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(HEADER_LINE)
    print(f" {timestamp}  |  Poll #{poll_number}")
    print(HEADER_LINE)
    print()

    print("GOLDEN SIGNALS")
    print(f"  Request Rate (req/s):     {metrics['request_rate']:.3f}")
    print(f"  P95 Latency (s):          {metrics['p95_latency']:.3f}")
    print(f"  Error Rate (%):           {metrics['error_rate'] * 100:.1f}")
    print(f"  Active Alerts:            {len(alerts)}")
    print()

    print("ACTIVE ALERTS")
    if not alerts:
        print("  (none)")
    else:
        for alert in alerts:
            labels = alert.get("labels", {})
            print(
                "  {name} | {severity} | firing for {duration}".format(
                    name=labels.get("alertname", "unknown"),
                    severity=labels.get("severity", "unknown"),
                    duration=format_duration(alert.get("startsAt")),
                )
            )
    print()

    print("RECENT METRICS (from Prometheus query API)")
    print(f"  http_requests_total:          {format_total(metrics['http_requests_total'])}")
    print(f"  url_redirects_total:          {format_total(metrics['url_redirects_total'])}")
    print(f"  url_created_total:            {format_total(metrics['url_created_total'])}")
    print(f"  db_errors_total:              {format_total(metrics['db_errors_total'])}")
    print()

    if alerts:
        print("🔴 FIRING  One or more alerts are active.")
    if metrics["error_rate"] > 0.05:
        print("⚠ WARNING  Error rate is above 5%.")
    if not alerts and metrics["error_rate"] <= 0.05:
        print("✅ HEALTHY  No active alerts and error rate is within threshold.")
    print()


def collect_metrics(prometheus_base_url):
    request_rate = sum_values(
        prometheus_query(prometheus_base_url, "rate(http_requests_total[1m])")
    )
    p95_latency = single_value(
        prometheus_query(
            prometheus_base_url,
            "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))",
        )
    )
    error_rate = single_value(
        prometheus_query(
            prometheus_base_url,
            "sum(rate(http_requests_total{status=~\"[45]..\"}[2m])) / sum(rate(http_requests_total[2m]))",
        )
    )
    http_requests_total = sum_values(
        prometheus_query(prometheus_base_url, "http_requests_total")
    )
    url_redirects_total = sum_values(
        prometheus_query(prometheus_base_url, "url_redirects_total")
    )
    url_created_total = sum_values(
        prometheus_query(prometheus_base_url, "url_created_total")
    )
    db_errors_total = sum_values(
        prometheus_query(prometheus_base_url, "db_errors_total")
    )

    return {
        "request_rate": request_rate,
        "p95_latency": p95_latency,
        "error_rate": error_rate,
        "http_requests_total": http_requests_total,
        "url_redirects_total": url_redirects_total,
        "url_created_total": url_created_total,
        "db_errors_total": db_errors_total,
    }


def main():
    args = parse_args()
    prometheus_base_url = args.prometheus.rstrip("/")
    alertmanager_base_url = args.alertmanager.rstrip("/")
    interval = max(1, args.interval)
    poll_number = 1

    try:
        while True:
            metrics = collect_metrics(prometheus_base_url)
            alerts = alertmanager_active_alerts(alertmanager_base_url)
            print_block(poll_number, metrics, alerts)
            poll_number += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped alert watcher.", flush=True)


if __name__ == "__main__":
    main()
