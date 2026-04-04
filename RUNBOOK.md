# URL Shortener Incident Response Runbook

## Service Overview
The stack has five primary components: the Flask URL shortener app, PostgreSQL for persistence, Prometheus for scraping and alert evaluation, Grafana for dashboards, and Alertmanager for routing notifications to Discord. Use `127.0.0.1` instead of `localhost` on Windows when browser or curl requests to `localhost` prefer IPv6 and fail.

## Alert Latency Budget
Prometheus scrapes the app every `10s` and evaluates rules every `15s`, so worst-case detection time is `25s`.

- `ServiceDown`: `25s detection + 60s for + 30s group_wait = 115s` worst-case alert latency.
- `HighErrorRate`: `25s detection + 120s for + 30s group_wait = 175s` worst-case alert latency.

Both alert paths are under the 5-minute response objective.

## Alert Playbooks
### ServiceDown
What it means: Prometheus cannot scrape the `url-shortener` target and the app is probably down, restarting, or unreachable on the container network.

Immediate steps:
1. Confirm the alert in Prometheus and Alertmanager.
2. Run `docker compose ps` and look for `app` in `Restarting`, `Exited`, or `unhealthy` state.
3. Run `docker compose logs --tail=100 app` and look for startup exceptions, import failures, or database connection errors.
4. Check `curl.exe -4 http://127.0.0.1:5000/health` from the host.
5. If the container is hung, restart it with `docker compose restart app`.
6. If the latest deploy broke startup, redeploy the previous known-good image.

How to verify it is resolved:
1. `curl.exe -4 http://127.0.0.1:5000/health` returns `200`.
2. Prometheus target `url-shortener` shows `UP`.
3. Alertmanager marks `ServiceDown` as resolved and Discord receives the resolved notification.

### HighErrorRate
What it means: More than 5% of HTTP responses have been `4xx` or `5xx` for at least two minutes.

Immediate steps:
1. Open Grafana and confirm the `Error Rate %` panel is above `5`.
2. Query Prometheus to split errors by status code family.
3. Check recent JSON logs for `db_error`, `short_code_generation_failed`, or repeated `not_found` spikes.
4. If errors are mostly `404`, validate test traffic or bad short codes.
5. If errors are `500`, inspect app logs and database health first.

How to verify it is resolved:
1. `Error Rate %` returns below `5`.
2. Prometheus shows the alert in `resolved` state.
3. Discord receives the resolved notification.

### SlowResponseTime
What it means: p95 latency is above 1 second for at least two minutes and users will feel the app slowing down even if it is not fully down.

Immediate steps:
1. Open Grafana and confirm `P95 Latency` is elevated.
2. Check `Request Rate` to see if this is load-driven or an internal bottleneck.
3. Run `curl.exe -4 http://127.0.0.1:5000/system` and inspect CPU and memory pressure.
4. Check `docker compose logs --tail=100 app` for slow database operations or timeout errors.
5. If the slowdown comes from synthetic load, stop the simulator first to stabilize the service.
6. If real traffic caused it, inspect the hottest query paths, especially `/urls` and redirect lookups.

How to verify it is resolved:
1. `P95 Latency` falls below `1s`.
2. `/health` remains `200`.
3. The alert resolves in Alertmanager.

### HighCPU
What it means: The app is using more than 90% CPU for at least two minutes and request backlog or CPU-bound work is likely building.

Immediate steps:
1. Open Grafana and confirm CPU is above the red threshold.
2. Run `curl.exe -4 http://127.0.0.1:5000/system` to confirm CPU saturation outside Grafana.
3. Check whether `/simulate/cpu` or another load test is running.
4. Inspect `docker compose logs --tail=100 app` for retry loops, hot endpoints, or repeated exception handling.
5. Reduce synthetic traffic or restart the app if it is stuck in a bad loop.
6. If CPU remains high after traffic drops, inspect the most recent code change before scaling up.

How to verify it is resolved:
1. CPU returns below `90%`.
2. Request latency trends down with it.
3. Alertmanager resolves the alert.

## Diagnostic Commands
Use these first:

```powershell
docker compose ps
docker compose logs --tail=100 app
docker compose logs --tail=100 db
docker stats --no-stream
curl.exe -4 http://127.0.0.1:5000/health
curl.exe -4 http://127.0.0.1:5000/system
curl.exe -4 http://127.0.0.1:5000/metrics
```

Prometheus query examples:

```text
http://127.0.0.1:9090/graph?g0.expr=sum(rate(http_requests_total[1m]))&g0.tab=0
http://127.0.0.1:9090/graph?g0.expr=histogram_quantile(0.95%2C%20sum(rate(http_request_duration_seconds_bucket%5B5m%5D))%20by%20(le))&g0.tab=0
http://127.0.0.1:9090/graph?g0.expr=100%20*%20(sum(rate(http_requests_total%7Bstatus%3D~%22%5B45%5D..%22%7D%5B2m%5D))%20%2F%20sum(rate(http_requests_total%5B2m%5D)))&g0.tab=0
http://127.0.0.1:9090/graph?g0.expr=system_cpu_percent&g0.tab=0
```

## Escalation
Escalate immediately if:
1. `ServiceDown` persists for more than 10 minutes.
2. `HighErrorRate` stays above `10%` after one rollback or restart attempt.
3. CPU or latency stays in the red after synthetic traffic has been removed.
4. PostgreSQL is unavailable or data integrity is in doubt.

Gather this before escalating:
1. The alert name, start time, and current state.
2. A screenshot of the relevant Grafana panels.
3. The last 100 lines of app logs.
4. The output of `/system`.
5. The exact command or deploy that happened just before the incident.

## Post-Incident
Checklist:
1. Confirm `/health` is `200` and the Grafana panels are back to baseline.
2. Confirm Alertmanager and Discord both show resolved notifications.
3. Save screenshots of the dashboard, alerts, and key logs.
4. Update the expected baseline for traffic, latency, and CPU if the new normal changed.
5. Write the incident summary and action items in `POST_INCIDENT_REPORT.md`.
