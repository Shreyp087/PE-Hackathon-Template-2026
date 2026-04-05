import json
import os
from datetime import datetime, UTC
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request


HOST = "0.0.0.0"
PORT = int(os.getenv("DISCORD_RELAY_PORT", "8080"))
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()


def _render_content(payload):
    alerts = payload.get("alerts") or []
    overall_status = str(payload.get("status") or "unknown").upper()
    header = f"[Alertmanager] {overall_status} - {len(alerts)} alert(s)"

    lines = [header]
    for alert in alerts[:10]:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        starts_at = alert.get("startsAt") or "unknown"
        alert_name = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown").upper()
        summary = annotations.get("summary") or "No summary provided"
        description = annotations.get("description") or ""
        lines.append(f"- {alert_name} [{severity}]")
        lines.append(f"  Summary: {summary}")
        if description:
            lines.append(f"  Detail: {description}")
        lines.append(f"  Starts: {starts_at}")

    truncated_count = max(0, len(alerts) - 10)
    if truncated_count:
        lines.append(f"...and {truncated_count} more alert(s)")

    lines.append(f"Forwarded at {datetime.now(UTC).isoformat()}")
    return "\n".join(lines)[:1900]


class DiscordRelayHandler(BaseHTTPRequestHandler):
    server_version = "DiscordRelay/1.0"

    def log_message(self, format, *args):
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "INFO",
                    "component": "discord_relay",
                    "message": format % args,
                }
            )
        )

    def do_POST(self):
        if self.path != "/alert":
            self.send_response(404)
            self.end_headers()
            return

        if not WEBHOOK_URL:
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"DISCORD_WEBHOOK_URL is not configured; alert skipped")
            print(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "level": "WARNING",
                        "component": "discord_relay",
                        "message": "webhook_not_configured",
                    }
                )
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8") or "{}")
            discord_payload = json.dumps({"content": _render_content(payload)}).encode(
                "utf-8"
            )

            discord_request = request.Request(
                WEBHOOK_URL,
                data=discord_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(discord_request, timeout=10) as response:
                response.read()

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        except Exception as exc:  # pragma: no cover - best-effort relay logging
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            print(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "level": "ERROR",
                        "component": "discord_relay",
                        "message": "relay_failed",
                        "error": str(exc),
                    }
                )
            )


def main():
    server = ThreadingHTTPServer((HOST, PORT), DiscordRelayHandler)
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "component": "discord_relay",
                "message": "relay_started",
                "host": HOST,
                "port": PORT,
            }
        )
    )
    if not WEBHOOK_URL:
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "WARNING",
                    "component": "discord_relay",
                    "message": "relay_running_without_webhook",
                }
            )
        )
    server.serve_forever()


if __name__ == "__main__":
    main()
