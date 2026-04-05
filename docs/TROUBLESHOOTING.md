# Troubleshooting Guide

When anomalies appear naturally or during a deployment process, refer to the following common failure scenarios before escalating the issue. First level debug response typically begins by evaluating logs: `docker compose logs -f <service_name>`.

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| **App won't start** | Missing or malformed `.env` file | Ensure the `.env` file executes correctly at the root folder and variables like `DB_PASSWORD` or `SECRET_KEY` are formatted properly without syntax errors. Check `docker compose logs app` to isolate startup parsing errors. |
| **DB connection refused** | Incorrect DB target (local container vs managed DB), bad credentials, or trusted-source/network restriction | For local DB: verify `db` container health with `docker compose ps db` and set `DB_HOST=db`. For managed DB: verify `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`, allow Droplet IP or VPC in provider trusted sources, and test connectivity from app container. |
| **`/metrics` returns 404** | Flask Prometheus middleware exporter is not initialized or routed | Check `app/__init__.py` to ensure the metrics exposition logic/blueprint is correctly registered. Verify the application server is importing the package cleanly. |
| **Short URL returns 404** | The shortcode identifier does not exist within the PostgreSQL table | Confirm via database query that the URL hash mapping was physically created. If testing a recently generated batch, retry the `seed.py` routine to verify data seeding succeeded. |
| **High memory usage** | Accumulation of uncapped data connections or Prometheus dense metric scraping | Scale Droplet size to 2GB+. Regulate memory scaling by configuring `storage.tsdb.retention.time` inside the Prometheus boot flags to retain fewer historical data points. |
| **Container keeps restarting** | The application process is repeatedly encountering a fatal unhandled exception | Isolate the application crashing cycle (`docker logs <container_id>`) specifically looking for module failures, unhandled exceptions, and Python traceback cascades to locate the underlying trigger. |
