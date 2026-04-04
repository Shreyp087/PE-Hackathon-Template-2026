# Incident Runbook

## Service Overview
This service is a Flask URL shortener running in Docker. The `app` container serves the API, redirect traffic, and a browser control center on port `5000`. PostgreSQL stores users, URLs, and events. Prometheus scrapes `/metrics` from the app and evaluates alert rules. Grafana shows dashboards for traffic, latency, errors, saturation, and active URLs. Alertmanager sends firing alerts to Discord. If `localhost` fails on Windows, use `127.0.0.1` for browser and `curl` checks.

## Alert Playbooks

### ServiceDown
What it means: Prometheus cannot scrape the `url-shortener` target. The app is down, not reachable, or failing before `/metrics` responds.

Immediate steps:
1. Check container state: `docker compose ps`
2. If `app` is restarting or exited, tail logs: `docker compose logs --tail=200 app`
3. Confirm Postgres is up: `docker compose ps db`
4. Test the app directly: `curl -i http://127.0.0.1:5000/health`
5. If the app is not running, restart it: `docker compose restart app`
6. If startup fails with database errors, inspect DB logs: `docker compose logs --tail=200 db`
7. If the app still will not start, capture logs and escalate.

How to verify it is resolved:
1. `curl -i http://127.0.0.1:5000/health` returns `200`.
2. `curl -s http://127.0.0.1:5000/metrics | head` returns Prometheus metrics.
3. `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=up{job=\"url-shortener\"}"` shows value `1`.
4. The `ServiceDown` alert clears in Alertmanager or Discord.

### HighErrorRate
What it means: More than 5% of recent requests are returning `5xx`. The app is alive, but it is failing requests.

Immediate steps:
1. Tail app logs: `docker compose logs --tail=200 -f app`
2. Look for recent `500`, `database_error`, timeout, or connection errors.
3. Check app health anyway: `curl -i http://127.0.0.1:5000/health`
4. Check system stats: `curl -s http://127.0.0.1:5000/system`
5. Check whether Postgres is overloaded or refusing connections: `docker compose exec db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from pg_stat_activity;"'`
6. Query Prometheus to confirm the error spike: `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=100 * sum(rate(http_requests_total{status=~\"5..\"}[2m])) / sum(rate(http_requests_total[2m]))"`
7. If the issue is tied to one endpoint, reproduce it with `curl` and isolate the failing route.
8. If needed, restart only the app after capturing logs: `docker compose restart app`

How to verify it is resolved:
1. New requests stop returning `5xx`.
2. The Prometheus error-rate query falls below `5`.
3. App logs no longer show repeated exceptions.
4. The `HighErrorRate` alert clears after the next evaluation windows.

### SlowResponseTime
What it means: P95 latency is above `1s`. The service is responding, but too slowly for a meaningful portion of traffic.

Immediate steps:
1. Open Grafana and confirm which time window and panel are spiking.
2. Check app logs for slow queries, retries, or repeated errors: `docker compose logs --tail=200 app`
3. Check `/system`: `curl -s http://127.0.0.1:5000/system`
4. Check DB activity: `docker compose exec db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select state, count(*) from pg_stat_activity group by state;"'`
5. Query Prometheus directly: `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))"`
6. If CPU or DB connections are saturated, treat that as the primary issue first.
7. If latency is isolated to one path, test it directly with `curl -w "%{time_total}\n"` and capture the result.

How to verify it is resolved:
1. The P95 Prometheus query drops below `1`.
2. Grafana shows the latency panel recovering.
3. Manual test requests complete quickly and consistently.
4. The `SlowResponseTime` alert clears.

### HighCPU
What it means: CPU usage for the app process is sustained above the alert threshold. The service may slow down or start failing next.

Immediate steps:
1. Confirm the spike in Grafana or Prometheus.
2. Check container status: `docker compose ps`
3. Check app logs for tight loops, bursts of traffic, or repeated failures: `docker compose logs --tail=200 app`
4. Check `/system`: `curl -s http://127.0.0.1:5000/system`
5. Query Prometheus directly: `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=sum(rate(process_cpu_seconds_total{job=\"url-shortener\"}[2m]))"`
6. If traffic is normal but CPU is high, restart the app after collecting logs: `docker compose restart app`
7. If CPU remains high after restart, escalate with logs and metrics screenshots.

How to verify it is resolved:
1. CPU query falls below the alert threshold.
2. `/system` shows lower CPU percent.
3. Request latency and error rate do not rise during or after the fix.
4. The `HighCPU` alert clears.

## Diagnostic Commands

| Purpose | Command |
| --- | --- |
| Check container status | `docker compose ps` |
| Tail app logs | `docker compose logs --tail=200 -f app` |
| Tail database logs | `docker compose logs --tail=200 -f db` |
| Open browser control center | `http://127.0.0.1:5000/` |
| Check DB connections | `docker compose exec db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from pg_stat_activity;"'` |
| Check DB activity by state | `docker compose exec db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select state, count(*) from pg_stat_activity group by state;"'` |
| Hit health endpoint | `curl -i http://127.0.0.1:5000/health` |
| Hit system endpoint | `curl -s http://127.0.0.1:5000/system` |
| Check metrics endpoint | `curl -s http://127.0.0.1:5000/metrics | head -40` |
| Query Prometheus target health | `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=up{job=\"url-shortener\"}"` |
| Query Prometheus error rate | `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=100 * sum(rate(http_requests_total{status=~\"5..\"}[2m])) / sum(rate(http_requests_total[2m]))"` |
| Query Prometheus P95 latency | `curl -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))"` |

## Escalation
Escalate immediately if any of these are true:
1. `ServiceDown` lasts more than `10` minutes.
2. You cannot restore service after one safe restart.
3. Postgres is down, refusing connections, or appears to have data corruption.
4. Error rate or latency stays elevated after the obvious fix.
5. You see repeated crashes, schema issues, or missing data.

Gather this information before escalating:
1. Exact alert name and the time it started.
2. Output of `docker compose ps`.
3. Last `200` lines of `app` logs and `db` logs.
4. Result of `/health` and `/system`.
5. Relevant Prometheus query output or Grafana screenshot.
6. What you already tried and what changed.

## Post-Incident
Checklist:
1. Confirm the alert is cleared and the service is stable.
2. Confirm `/health`, `/system`, and `/metrics` all respond correctly.
3. Confirm Grafana panels are back within normal range.
4. Update the expected baseline if traffic or behavior changed for a legitimate reason.
5. Write a one-paragraph incident summary covering impact, root cause, fix, and follow-up actions.
