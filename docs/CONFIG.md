# Environment Configuration

Use this guide to configure the `.env` file at the repository root.

## Required Variables

| Name | Description | Example Value |
|------|-------------|---------------|
| `DB_NAME` | PostgreSQL database name used by the app. | `hackathon_db` |
| `DB_USER` | PostgreSQL username. | `postgres` |
| `DB_PASSWORD` | PostgreSQL password. | `postgres` |
| `DB_HOST` | Database host: `localhost` for local app runtime, `db` for docker-compose runtime, or managed DB hostname for production. | `localhost` |
| `DB_PORT` | Database port: `5432` for local/containerized DB or managed DB port from provider. | `5432` |

## Optional Variables

| Name | Description | Example Value |
|------|-------------|---------------|
| `FLASK_DEBUG` | Enables Flask debug mode. Use `false` in production. | `true` |
| `DISCORD_WEBHOOK_URL` | Discord webhook used by the `discord-relay` service for alert notifications. | `https://discord.com/api/webhooks/...` |
| `DB_HOST_PORT` | Host port mapped to Postgres in `docker-compose.yml`. Only needed when changing host mapping. | `5432` |
| `GUNICORN_WORKERS` | Number of Gunicorn workers for production container runtime. | `2` |
| `APP_IMAGE` | Image override used in deployment/rollback workflows. | `url-shortener:rollback` |

## Recommended Profiles

Local app + Docker DB:

```env
DB_HOST=localhost
DB_PORT=5432
```

Docker Compose app + Docker DB:

```env
DB_HOST=db
DB_PORT=5432
```

Managed PostgreSQL (DigitalOcean):

```env
DB_HOST=<managed-db-hostname>
DB_PORT=<managed-db-port>
DB_NAME=<managed-db-name>
DB_USER=<managed-db-user>
DB_PASSWORD=<managed-db-password>
```

Durability note:
- If you keep local/containerized PostgreSQL in production, schedule daily `pg_dump` backups to object storage (DigitalOcean Spaces/S3).
- If you use managed PostgreSQL, enable automated backups and point-in-time recovery.
