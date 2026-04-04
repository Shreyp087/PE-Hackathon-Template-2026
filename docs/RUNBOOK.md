# Incident Response Runbooks

This document contains standard operating procedures (runbooks) for the URL Shortener's critical monitoring alerts originating from Prometheus & Alertmanager. 

---

## Alert: Service Down (HTTP 5xx spike or health check failure)
- **Severity**: Critical 🔴
- **Symptoms**: The `/health` endpoint times out or returns non-200. Client requests are hit with `502 Bad Gateway` or `503 Service Unavailable`.
- **Immediate Actions**: 
  1. Validate whether the Load Balancer is marking the node as dead.
  2. SSH into the primary Droplet and run `docker compose ps` to check if the `app` container is running or stuck restarting.
- **Root Cause Investigation**:
  1. Inspect app logs: `docker compose logs --tail=100 app`. Look for unhandled exceptions or fatal Python module errors.
  2. Inspect system memory: `htop` or `docker stats` to verify if the container was OOMKilled by Linux due to leakages.
- **Resolution Steps**:
  1. Simply restart the application if it is hung: `docker compose restart app`.
  2. If the current image is fundamentally broken due to a recent bad deployment, execute a rollback immediately.
- **Escalation**: If application crashes persist and stack traces are non-obvious, escalate directly to the Senior Production Engineer.

---

## Alert: High Error Rate (>5% error rate for 2+ minutes)
- **Severity**: Warning 🟡 / Critical 🔴
- **Symptoms**: Grafana shows an elevated level of HTTP 4xx or 5xx responses globally. User bases report broken short links or failed generation.
- **Immediate Actions**: 
  1. Acknowledge the alert in the Discord/PagerDuty incident channel.
  2. Check Grafana dashboards to identify if mapped errors are strictly 4xx (Client/Not Found) or 5xx (Internal Server).
- **Root Cause Investigation**:
  1. If 404s, evaluate if the latest batch CSV seeding job failed, resulting in silently missing URLs.
  2. If 500s, filter docker logs for `ERROR` or explicit `Traceback` lines. Often points to bad JSON payloads or database timeout exceptions.
- **Resolution Steps**:
  1. Formally patch and hotfix the application code if isolated to a known regression.
  2. Purge and safely re-execute database seeding scripts if mapping data was organically lost or truncated at the schema level.
- **Escalation**: Escalate to the core Backend Developer team if a code hotfix is immediately required.

---

## Alert: High Latency (p95 > 500ms)
- **Severity**: Warning 🟡
- **Symptoms**: Request durations climb beyond safe UX margins on `/shorten` or `/` redirect paths. 
- **Immediate Actions**: 
  1. Verify if this anomaly strictly correlates with an influx/spike in inbound application traffic. 
  2. Review Droplet CPU and RAM utilization metrics instantly. 
- **Root Cause Investigation**:
  1. Access Grafana to check base Postgres query execution timings. 
  2. Elevated latencies regularly correlate with a lack of B-Tree indexing on massive lookup tables.
- **Resolution Steps**:
  1. Scale the droplet vertically (add temporary CPU limits) to absorb the immediate traffic spike.
  2. Long-term fix: Apply database indexes on heavily queried fields like `shortcode` or securely introduce a Redis caching layer for continuous reads.
- **Escalation**: Escalate to the Database Administrator or Architecture lead for sustained query performance tuning.

---

## Alert: Database Connection Exhausted
- **Severity**: Critical 🔴
- **Symptoms**: App logs flood aggressively with `peewee.OperationalError: FATAL: sorry, too many clients already`. Entire service becomes frozen to all basic IO traffic.
- **Immediate Actions**: 
  1. Forcibly stop any non-essential workloads actively querying the DB (e.g., ad-hoc large data imports, analytics dumps, cron scripts).
  2. Restart the app container to immediately detach and flush zombie connection pools: `docker compose restart app`.
- **Root Cause Investigation**:
  1. Check Postgres overall active connection limits (`max_connections` inside `postgresql.conf`).
  2. Heavily scrutinize application code to guarantee DB connections are properly closing (e.g., ensuring `teardown_appcontext` executes unconditionally).
- **Resolution Steps**:
  1. Introduce a dedicated connection pooler (like PgBouncer) externally to multiplex active backend queries securely.
  2. Expand `max_connections` in `postgresql.conf` if the Droplet memory safely permits.
- **Escalation**: Treat as highest priority. Escalate to the DevOps & Platform engineering team instantly.

---

## Alert: Disk Space Warning (>80% used)
- **Severity**: Warning 🟡
- **Symptoms**: The server filesystem breaches 80%+ utilization. Direct risk of critical database corruption mapping anomalies if it maxes 100%.
- **Immediate Actions**:
  1. Ping the developer team instructing them to halt any large data payload imports or localized system backups.
- **Root Cause Investigation**:
  1. Establish an SSH session and run `df -h` on the Droplet.
  2. Run `ncdu /` or `du -sh /*` to pinpoint the largest aggregated directories. This is typically sourced by unchecked Docker overlay networks, massive rotated log structures, or raw Prometheus TSDB database accumulation over time.
- **Resolution Steps**:
  1. Purge dangling docker resources thoroughly: `docker system prune -af`.
  2. Delete previously rotated compressed logs safely or gently truncate the Postgres WAL persistence logs.
  3. Seamlessly expand the block storage volume size inside the DigitalOcean dashboard and apply resize rules effectively to the filesystem.
- **Escalation**: Only escalate formally if disk space is consumed by rigid system data mapping protocols that strictly cannot be removed without an emergency volume restructuring intervention.
