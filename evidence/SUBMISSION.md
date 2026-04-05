# MLH PE Hackathon 2026 — Incident Response Submission
**Team:** Shrey Patel
**Live URL:** http://127.0.0.1:5000/
**Track:** Incident Response
**Tier Targeted:** Gold

---

## BRONZE

### B1 — JSON structured logging includes timestamp and log level fields

**Link:**
http://127.0.0.1:5000/logs/recent

**What this evidence shows:**
This screenshot is the original local `/logs/recent` response from the running project on `127.0.0.1`. It shows real structured JSON records emitted by the app, including `timestamp`, `level`, and `component`, after generating live `/health`, `/r/test404`, `/shorten`, and redirect traffic.

**Screenshot file:** B1_json_structured_logs.png

---

### B2 — A /metrics-style endpoint is available and returns monitoring data

**Link:**
http://127.0.0.1:5000/metrics

**What this evidence shows:**
These screenshots are original captures of the live `/metrics` endpoint exposed by the local app. They show the raw Prometheus exposition output, including `http_requests_total`, `http_request_duration_seconds`, `url_redirects_total`, `url_created_total`, and `db_errors_total`, plus standard process metrics.

**Screenshot file:** B2_metrics_endpoint.png

---

### B3 — Logs can be inspected through tooling without direct server SSH

**Link:**
http://127.0.0.1:5000/

**What this evidence shows:**
This screenshot is the original browser UI served by the project on `127.0.0.1:5000`. It shows the local control center with live system metrics, observability links, recent URLs, and recent structured logs, demonstrating that operators can inspect the service without SSH.

**Screenshot file:** B3_logs_no_ssh.png

---

## SILVER

### S1 — Alerting rules are configured for service down and high error rate

**Link:**
http://127.0.0.1:8765/monitoring/alerts.yml

**What this evidence shows:**
This is an original capture of the real `monitoring/alerts.yml` file served locally from the project itself. It shows the configured Prometheus rules for `ServiceDown`, `HighErrorRate`, `SlowResponseTime`, and `HighCPU`, including the expressions, severities, `for` durations, and annotations.

**Screenshot file:** S1_alert_rules.png

---

### S2 — Alerts are routed to an operator channel such as Slack or email

**Link:**
http://127.0.0.1:8765/monitoring/alertmanager.yml

**What this evidence shows:**
This is an original capture of the real `monitoring/alertmanager.yml` file served locally from the repo. It shows the `webhook_configs` receiver, `send_resolved: true`, the default routing settings, and inhibition rules used to route alerts through the local Discord relay.

**Screenshot file:** S2_discord_alert.png

---

### S3 — Alerting latency is documented and meets five-minute response objective

**Link:**
http://127.0.0.1:8765/RUNBOOK.md

**What this evidence shows:**
This screenshot is an original capture of the real `RUNBOOK.md` file served locally. It shows the documented alert latency budget proving that `ServiceDown` reaches notification in about 115 seconds and `HighErrorRate` in about 175 seconds, both under the five-minute objective.

**Screenshot file:** S3_alert_latency.png

---

## GOLD

### G1 — Dashboard evidence covers latency, traffic, errors, and saturation

**Link:**
https://link-shrink.duckdns.org/grafana/d/url-shortener-golden-signals/url-shortener-golden-signals?orgId=1&from=now-1h&to=now

**What this evidence shows:**
This is an original live screenshot from the local Grafana dashboard running on `127.0.0.1`. It captures the project's real Golden Signals dashboard with traffic, latency, errors, and saturation panels sourced from Prometheus.

**Screenshot file:** G1_grafana_dashboard.png

---

### G2 — Runbook includes actionable alert-response procedures

**Link:**
http://127.0.0.1:8765/RUNBOOK.md

**What this evidence shows:**
This is an original screenshot of the real runbook file from the project, served locally over `127.0.0.1`. It focuses on the actionable incident procedure sections so a judge can verify that the response playbooks are concrete and operational.

**Screenshot file:** G2_runbook.png

---

### G3 — Root-cause analysis of a simulated incident is documented

**Link:**
http://127.0.0.1:8765/POST_INCIDENT_REPORT.md

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
