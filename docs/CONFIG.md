# Environment Configuration

Reference this guide to appropriately define application environments through secrets securely. Configure these keys directly within your `.env` repository root context.

| Name | Description | Example Value | Required/Optional |
|------|-------------|---------------|-------------------|
| `DATABASE_URL` | The fully qualified connection string for pointing directly to the PostgreSQL database in lieu of separated constants. | `postgresql://user:pass@db:5432/hackathon` | Optional |
| `DB_NAME` | Explicit name of the active PostgreSQL database instance mapped to peewee. | `hackathon_db` | Required |
| `DB_USER` | Targeted database system username payload. | `postgres` | Required |
| `DB_PASSWORD` | Encrypted or plain superuser operational password to process database operations. | `supersecret` | Required |
| `DB_HOST` | Network hostname of the database server instances. | `db` (docker) or `localhost` (local) | Required |
| `SECRET_KEY` | Cryptographic secret utilized by Flask mapping HTTP sessions / verifying signed cookies tightly. | `c87s9d...` | Required |
| `REDIS_URL` | System connection URI connecting a Redis in-memory storage cluster (for eventual scalability & aggressive URL mapping caches). | `redis://redis:6379/1` | Optional |
| `PORT` | Network port mapped against the Flask listener. | `5000` | Optional |
| `LOG_LEVEL` | Enforced verbosity filter of python logging pipeline. (DEBUG, INFO, WARNING, ERROR). | `INFO` | Optional |
| `PROMETHEUS_PORT` | Exposure mapped network port binding exactly to the Prometheus scraping engine interfaces. | `9090` | Optional |
| `ALLOWED_HOSTS` | Security restriction representing a comma-separated whitelist limiting incoming `Host:` headers the load balancer routes explicitly. | `123.45.67.89,api.shortener.example` | Optional |
| `DEBUG` / `FLASK_DEBUG` | Enables native stack traceback output and hot-reloading file changes. **Warning: Must be evaluated explicitly as `false` in production!** | `false` | Required |
| `DISCORD_WEBHOOK_URL`| Remote Alertmanager callback destination webhook firing if monitoring thresholds report a system outage or unhandled application disruption. | `https://discord.com/api/web...` | Optional |
