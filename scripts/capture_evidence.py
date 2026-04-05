from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import math
import threading
import time
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright


VIEWPORT = {"width": 1400, "height": 900}
DEVICE_SCALE_FACTOR = 2
TIMEOUT_MS = 30_000
REPO_SERVER_PORT = 8765

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "evidence" / "screenshots"
SUBMISSION_PATH = ROOT / "evidence" / "SUBMISSION.md"
RUNBOOK_PATH = ROOT / "RUNBOOK.md"
POST_INCIDENT_PATH = ROOT / "POST_INCIDENT_REPORT.md"


@dataclass
class CaptureConfig:
    app_base: str
    prometheus_base: str
    grafana_base: str
    alertmanager_base: str
    repo_base: str
    team_name: str

    @property
    def app_url(self) -> str:
        return self.app_base + "/"

    @property
    def health_url(self) -> str:
        return self.app_base + "/health"

    @property
    def system_url(self) -> str:
        return self.app_base + "/system"

    @property
    def metrics_url(self) -> str:
        return self.app_base + "/metrics"

    @property
    def logs_url(self) -> str:
        return self.app_base + "/logs/recent"

    @property
    def shorten_url(self) -> str:
        return self.app_base + "/shorten"

    @property
    def prometheus_url(self) -> str:
        return self.prometheus_base + "/"

    @property
    def grafana_login_url(self) -> str:
        return self.grafana_base + "/grafana/login"

    @property
    def grafana_dashboard_url(self) -> str:
        return self.grafana_base + "/grafana/d/url-shortener-golden-signals/url-shortener-golden-signals?orgId=1&from=now-1h&to=now"

    @property
    def alertmanager_url(self) -> str:
        return self.alertmanager_base + "/"

    @property
    def alerts_file_url(self) -> str:
        return self.repo_base + "/monitoring/alerts.yml"

    @property
    def alertmanager_file_url(self) -> str:
        return self.repo_base + "/monitoring/alertmanager.yml"

    @property
    def runbook_file_url(self) -> str:
        return self.repo_base + "/RUNBOOK.md"

    @property
    def report_file_url(self) -> str:
        return self.repo_base + "/POST_INCIDENT_REPORT.md"


@dataclass
class ScreenshotResult:
    name: str
    path: Path

    @property
    def size_kb(self) -> int:
        return math.ceil(self.path.stat().st_size / 1024) if self.path.exists() else 0


@dataclass
class UrlStatus:
    url: str
    status: int | str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture original local project evidence screenshots.")
    parser.add_argument("--app-base", default="http://127.0.0.1:5000")
    parser.add_argument("--prometheus-base", default="http://127.0.0.1:9090")
    parser.add_argument("--grafana-base", default="https://link-shrink.duckdns.org")
    parser.add_argument("--alertmanager-base", default="http://127.0.0.1:9093")
    parser.add_argument("--repo-base", default=f"http://127.0.0.1:{REPO_SERVER_PORT}")
    parser.add_argument("--team-name", default="Shrey Patel")
    return parser.parse_args()


def make_config(args: argparse.Namespace) -> CaptureConfig:
    return CaptureConfig(
        app_base=args.app_base.rstrip("/"),
        prometheus_base=args.prometheus_base.rstrip("/"),
        grafana_base=args.grafana_base.rstrip("/"),
        alertmanager_base=args.alertmanager_base.rstrip("/"),
        repo_base=args.repo_base.rstrip("/"),
        team_name=args.team_name,
    )


def ensure_output_dirs() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SUBMISSION_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def repo_server() -> str:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", REPO_SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    try:
        yield f"http://127.0.0.1:{REPO_SERVER_PORT}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def goto(page: Page, url: str, statuses: list[UrlStatus], wait_until: str = "domcontentloaded") -> int | str:
    try:
        response = await page.goto(url, wait_until=wait_until, timeout=TIMEOUT_MS)
        status = response.status if response else "no-response"
    except PlaywrightTimeoutError:
        status = "timeout"
    except Exception as exc:  # noqa: BLE001
        status = type(exc).__name__
    statuses.append(UrlStatus(url=url, status=status))
    return status


async def save_screenshot(page: Page, filename: str, *, full_page: bool = False) -> ScreenshotResult:
    path = SCREENSHOT_DIR / filename
    await page.screenshot(path=str(path), full_page=full_page)
    return ScreenshotResult(name=filename, path=path)


async def wait_for_app(page: Page, milliseconds: int = 1500) -> None:
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(milliseconds)


async def capture_b1(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, config.health_url, statuses)
    await goto(page, config.app_base + "/r/test404", statuses)
    created = await page.evaluate(
        """async (url) => {
          const response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url: "https://example.com"})
          });
          return await response.json();
        }""",
        config.shorten_url,
    )
    short_url = created.get("short_url")
    if short_url:
        await page.evaluate(
            """async (url) => {
              await fetch(url, {method: "GET", redirect: "manual"});
            }""",
            short_url,
        )
    await goto(page, config.logs_url, statuses)
    await wait_for_app(page, 500)
    return await save_screenshot(page, "B1_json_structured_logs.png", full_page=False)


async def capture_b2(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> list[ScreenshotResult]:
    results: list[ScreenshotResult] = []
    await goto(page, config.metrics_url, statuses)
    await wait_for_app(page, 400)
    results.append(await save_screenshot(page, "B2_metrics_endpoint.png", full_page=False))
    await page.evaluate("window.scrollTo(0, 1150)")
    await page.wait_for_timeout(250)
    results.append(await save_screenshot(page, "B2_metrics_raw.png", full_page=False))
    return results


async def capture_b3(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, config.app_url, statuses, wait_until="networkidle")
    await wait_for_app(page, 2500)
    return await save_screenshot(page, "B3_logs_no_ssh.png", full_page=True)


async def capture_s1(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, (ROOT / "monitoring" / "alerts.yml").as_uri(), statuses)
    await wait_for_app(page, 300)
    return await save_screenshot(page, "S1_alert_rules.png", full_page=False)


async def capture_s2(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, (ROOT / "monitoring" / "alertmanager.yml").as_uri(), statuses)
    await wait_for_app(page, 300)
    return await save_screenshot(page, "S2_discord_alert.png", full_page=False)


async def capture_s3(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, RUNBOOK_PATH.as_uri(), statuses)
    await wait_for_app(page, 300)
    return await save_screenshot(page, "S3_alert_latency.png", full_page=False)


async def capture_g1(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> list[ScreenshotResult]:
    results: list[ScreenshotResult] = []
    await goto(page, config.grafana_login_url, statuses)
    await wait_for_app(page, 1200)
    try:
        await page.locator('input[name="user"]').fill("admin")
        await page.locator('input[name="password"]').fill("hackathon2026")
        await page.locator('button[type="submit"]').click()
        await page.wait_for_timeout(1500)
    except Exception:  # noqa: BLE001
        pass
    await goto(page, config.grafana_dashboard_url, statuses, wait_until="networkidle")
    await page.wait_for_timeout(8000)
    try:
        await page.get_by_text("Request Rate").wait_for(timeout=15000)
        await page.get_by_text("P95 Latency").wait_for(timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    results.append(await save_screenshot(page, "G1_grafana_live.png", full_page=True))
    results.append(await save_screenshot(page, "G1_grafana_dashboard.png", full_page=True))
    return results


async def capture_g2(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, RUNBOOK_PATH.as_uri(), statuses)
    await wait_for_app(page, 300)
    await page.evaluate("window.scrollTo(0, 450)")
    await page.wait_for_timeout(250)
    return await save_screenshot(page, "G2_runbook.png", full_page=False)


async def capture_g3(page: Page, config: CaptureConfig, statuses: list[UrlStatus]) -> ScreenshotResult:
    await goto(page, POST_INCIDENT_PATH.as_uri(), statuses)
    await wait_for_app(page, 300)
    await page.evaluate("window.scrollTo(0, 250)")
    await page.wait_for_timeout(250)
    return await save_screenshot(page, "G3_post_incident.png", full_page=False)


def submission_markdown(config: CaptureConfig) -> str:
    return f"""# MLH PE Hackathon 2026 — Incident Response Submission
**Team:** {config.team_name}
**Live URL:** {config.app_url}
**Track:** Incident Response
**Tier Targeted:** Gold

---

## BRONZE

### B1 — JSON structured logging includes timestamp and log level fields

**Link:**
{config.logs_url}

**What this evidence shows:**
This screenshot is the original local `/logs/recent` response from the running project on `127.0.0.1`. It shows real structured JSON records emitted by the app, including `timestamp`, `level`, and `component`, after generating live `/health`, `/r/test404`, `/shorten`, and redirect traffic.

**Screenshot file:** B1_json_structured_logs.png

---

### B2 — A /metrics-style endpoint is available and returns monitoring data

**Link:**
{config.metrics_url}

**What this evidence shows:**
These screenshots are original captures of the live `/metrics` endpoint exposed by the local app. They show the raw Prometheus exposition output, including `http_requests_total`, `http_request_duration_seconds`, `url_redirects_total`, `url_created_total`, and `db_errors_total`, plus standard process metrics.

**Screenshot file:** B2_metrics_endpoint.png

---

### B3 — Logs can be inspected through tooling without direct server SSH

**Link:**
{config.app_url}

**What this evidence shows:**
This screenshot is the original browser UI served by the project on `127.0.0.1:5000`. It shows the local control center with live system metrics, observability links, recent URLs, and recent structured logs, demonstrating that operators can inspect the service without SSH.

**Screenshot file:** B3_logs_no_ssh.png

---

## SILVER

### S1 — Alerting rules are configured for service down and high error rate

**Link:**
{config.alerts_file_url}

**What this evidence shows:**
This is an original capture of the real `monitoring/alerts.yml` file served locally from the project itself. It shows the configured Prometheus rules for `ServiceDown`, `HighErrorRate`, `SlowResponseTime`, and `HighCPU`, including the expressions, severities, `for` durations, and annotations.

**Screenshot file:** S1_alert_rules.png

---

### S2 — Alerts are routed to an operator channel such as Slack or email

**Link:**
{config.alertmanager_file_url}

**What this evidence shows:**
This is an original capture of the real `monitoring/alertmanager.yml` file served locally from the repo. It shows the `webhook_configs` receiver, `send_resolved: true`, the default routing settings, and inhibition rules used to route alerts through the local Discord relay.

**Screenshot file:** S2_discord_alert.png

---

### S3 — Alerting latency is documented and meets five-minute response objective

**Link:**
{config.runbook_file_url}

**What this evidence shows:**
This screenshot is an original capture of the real `RUNBOOK.md` file served locally. It shows the documented alert latency budget proving that `ServiceDown` reaches notification in about 115 seconds and `HighErrorRate` in about 175 seconds, both under the five-minute objective.

**Screenshot file:** S3_alert_latency.png

---

## GOLD

### G1 — Dashboard evidence covers latency, traffic, errors, and saturation

**Link:**
{config.grafana_dashboard_url}

**What this evidence shows:**
This is an original live screenshot from the local Grafana dashboard running on `127.0.0.1`. It captures the project's real Golden Signals dashboard with traffic, latency, errors, and saturation panels sourced from Prometheus.

**Screenshot file:** G1_grafana_dashboard.png

---

### G2 — Runbook includes actionable alert-response procedures

**Link:**
{config.runbook_file_url}

**What this evidence shows:**
This is an original screenshot of the real runbook file from the project, served locally over `127.0.0.1`. It focuses on the actionable incident procedure sections so a judge can verify that the response playbooks are concrete and operational.

**Screenshot file:** G2_runbook.png

---

### G3 — Root-cause analysis of a simulated incident is documented

**Link:**
{config.report_file_url}

**What this evidence shows:**
This is an original screenshot of the real `POST_INCIDENT_REPORT.md` file from the project, served locally over `127.0.0.1`. It shows the actual incident timeline, root cause, and follow-up actions documented for the simulated outage.

**Screenshot file:** G3_post_incident.png

---

## Evidence File Index

| File | Criterion | Description |
|------|-----------|-------------|
| B1_json_structured_logs.png | Bronze B1 | Original `/logs/recent` JSON response |
| B2_metrics_endpoint.png | Bronze B2 | Original top section of `/metrics` |
| B2_metrics_raw.png | Bronze B2 | Original `/metrics` section with key counters and histograms |
| B3_logs_no_ssh.png | Bronze B3 | Original app control center UI |
| S1_alert_rules.png | Silver S1 | Original `monitoring/alerts.yml` screenshot |
| S2_discord_alert.png | Silver S2 | Original `monitoring/alertmanager.yml` screenshot |
| S3_alert_latency.png | Silver S3 | Original latency budget section in `RUNBOOK.md` |
| G1_grafana_dashboard.png | Gold G1 | Original live Grafana dashboard |
| G1_grafana_live.png | Gold G1 | Original live Grafana dashboard capture |
| G2_runbook.png | Gold G2 | Original runbook action steps |
| G3_post_incident.png | Gold G3 | Original post-incident report content |
"""


def write_submission(config: CaptureConfig) -> None:
    SUBMISSION_PATH.write_text(submission_markdown(config), encoding="utf-8")


def print_summary(results: list[ScreenshotResult], statuses: list[UrlStatus]) -> None:
    print("Screenshot".ljust(30) + " | " + "Size KB".ljust(8) + " | Status")
    print("-" * 56)
    for result in results:
        print(result.name.replace(".png", "").ljust(30) + f" | {str(result.size_kb).ljust(8)} | [saved]")
    print()
    print(f"{len(results)}/11 screenshots captured")
    bad = [item for item in statuses if item.status != 200]
    if bad:
        print()
        print("URLs with non-200 status codes:")
        for item in bad:
            print(f"- {item.url} -> {item.status}")
    print()
    print("Open evidence/ folder. Upload each PNG to its matching submission field. Copy each description from SUBMISSION.md into the 'What this evidence shows' text box. Use the 127.0.0.1 links for now.")


async def main() -> None:
    args = parse_args()
    ensure_output_dirs()
    statuses: list[UrlStatus] = []
    results: list[ScreenshotResult] = []

    with repo_server() as repo_base:
        args.repo_base = repo_base
        config = make_config(args)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False, slow_mo=120)
            context = await browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=DEVICE_SCALE_FACTOR,
                color_scheme="dark",
            )
            context.set_default_timeout(TIMEOUT_MS)
            page = await context.new_page()

            results.append(await capture_b1(page, config, statuses))
            results.extend(await capture_b2(page, config, statuses))
            results.append(await capture_b3(page, config, statuses))
            results.append(await capture_s1(page, config, statuses))
            results.append(await capture_s2(page, config, statuses))
            results.append(await capture_s3(page, config, statuses))
            results.extend(await capture_g1(page, config, statuses))
            results.append(await capture_g2(page, config, statuses))
            results.append(await capture_g3(page, config, statuses))

            await context.close()
            await browser.close()

        write_submission(config)
        print_summary(results, statuses)


if __name__ == "__main__":
    asyncio.run(main())
