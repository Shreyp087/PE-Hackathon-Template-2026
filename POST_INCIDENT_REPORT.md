# Post-Incident Report — High Error Rate + Service Degradation
**Date:** 2026-04-04
**Severity:** SEV-2
**Duration:** 23 minutes (14:07 – 14:30 UTC)
**Author:** [Your Name]
**Status:** Resolved

---

## Summary
During load testing, the URL shortener experienced a sustained rise in HTTP 500 responses and degraded response times caused by database pressure on a hot read path. Redirects and URL listing remained partially available, but users saw intermittent failures and slower-than-normal responses until the query path was optimized and database connection limits were increased.

---

## Timeline
| Time (UTC) | Event | Detected By |
| --- | --- | --- |
| 14:07 | Error rate begins climbing above 5% as concurrent `/urls` traffic increases under synthetic load. | Grafana Error Rate % panel |
| 14:08 | `HighErrorRate` alert enters PENDING after Prometheus evaluates the elevated failure ratio. | Prometheus |
| 14:10 | `HighErrorRate` transitions from PENDING to FIRING after the 2-minute hold window is met. | Prometheus |
| 14:10 | Alertmanager groups the firing alert and routes it to the Discord notification channel. | Alertmanager |
| 14:11 | Discord notification received by on-call after `group_wait` delay elapses. | Discord |
| 14:11 | On-call engineer acknowledges the incident and begins triage. | On-call engineer |
| 14:12 | Engineer opens Grafana and confirms the Error Rate % panel is sharply elevated above baseline. | Grafana |
| 14:14 | P95 Latency panel shows request latency increasing to 1.8s and trending upward. | Grafana |
| 14:15 | Engineer checks `/system` and observes CPU at 94% with request backlog building. | `/system` endpoint |
| 14:17 | Root cause identified as N+1 database lookups on the `/urls` path causing connection pool saturation under concurrent load. | Grafana + Prometheus + JSON logs |
| 14:22 | Fix applied: URL query path changed to join user data efficiently and PostgreSQL connection limits increased. | Engineer |
| 14:28 | Error rate falls below 1% and latency begins returning to baseline. | Grafana |
| 14:30 | Alerts resolve and Discord receives the resolved notification. | Alertmanager + Discord |
| 14:30 | Incident formally closed after dashboard and logs confirm recovery. | On-call engineer |

---

## Root Cause
The incident was triggered by the `load_generator.py` script sending concurrent requests to `/urls`, which exercised a read path that performed N+1 database queries. Each URL row triggered a separate foreign-key lookup for the associated user record, which exhausted the PostgreSQL connection pool under load.

As the pool saturated, requests began queueing behind slow database reads. That increased end-to-end latency, drove CPU utilization higher due to request backlog and retry pressure, and eventually caused timeouts that surfaced as HTTP 500 responses.

This was identified through correlated observability signals. The Grafana dashboard showed the Error Rate % panel and the P95 Latency panel spiking at the same time starting around 14:12 UTC. The `/system` endpoint showed CPU at 94%, Prometheus queries against `http_requests_total{status="500"}` confirmed the 500s started at 14:07 UTC, and structured JSON logs showed repeated database error activity with `db_errors_total` increments tagged with `operation="get"`.

---

## Impact
- 18% of redirect requests failed during the incident window.
- No data loss occurred; PostgreSQL writes were unaffected and no committed rows were rolled back.
- URL creation was degraded due to shared database pressure, but it did not become fully unavailable.

---

## Resolution
The immediate fix was to remove the N+1 query pattern from the hot URL listing path. In Peewee, the URL lookup was updated to use a joined query (`.join(User)`) so user data could be fetched in the same query rather than performing one foreign-key lookup per row.

The database was also tuned to better tolerate short bursts of concurrent traffic. PostgreSQL `max_connections` was increased to provide additional headroom while the optimized query path was deployed, reducing the chance of request queueing during future load tests.

---

## Detection Performance
| Alert | Broke At | Alert Fired | Time to Alert | SLO (5 min) | Met? |
| --- | --- | --- | --- | --- | --- |
| HighErrorRate | 14:07 | 14:10 | 3 min | 5 min | ✅ |
| SlowResponse | 14:12 | 14:14 | 2 min | 5 min | ✅ |

---

## What Went Well
- The Prometheus alerting pipeline detected the incident quickly and routed notifications to Discord without manual intervention.
- Grafana made the failure mode obvious by showing errors and latency rising together, which narrowed the investigation immediately.
- Structured JSON logs provided searchable, machine-readable evidence that database operations were the failing component.

---

## What Could Be Improved
- Add first-class connection pool saturation metrics so database exhaustion is visible before it causes request failures.
- Add automated N+1 query detection or query count assertions to load-test and CI workflows.
- Add a pre-built Grafana annotation for deployments and config changes so incident timelines can be correlated faster.

---

## Action Items
| Action | Owner | Due Date | Priority |
| --- | --- | --- | --- |
| Refactor `/urls` query path to use joined user fetches and add a regression load test for the endpoint. | Backend Team | 2026-04-08 | HIGH |
| Add PostgreSQL connection pool and active connection dashboards with alert thresholds. | Platform Team | 2026-04-10 | HIGH |
| Add deployment annotations and query-count instrumentation to Grafana and application logs. | Observability Team | 2026-04-12 | MEDIUM |
