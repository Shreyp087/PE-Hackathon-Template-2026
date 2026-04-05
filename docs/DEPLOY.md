# DigitalOcean Deployment Guide (Production-Ready)

This runbook deploys the full stack (app + PostgreSQL + Prometheus + Alertmanager + Grafana) on a single DigitalOcean Droplet.

Why this is the best fit for this codebase:
- Your repository is already packaged for multi-container deployment with Docker Compose.
- Monitoring is bundled and prewired in compose.
- Fastest, lowest-risk path for hackathon delivery.

## 0. Codebase Audit Findings (Important Before Deploy)

Validated from this repository:
- App starts with Gunicorn in container on port 5000.
- Prometheus scrapes app using internal service DNS (`app:5000`).
- Alertmanager routes alerts to an internal `discord-relay` service.
- `discord-relay` forwards to `DISCORD_WEBHOOK_URL` when configured.
- The compose app service currently sets `DB_PORT` from `.env`.

Critical gotcha to avoid downtime:
- In Docker, PostgreSQL listens internally on port `5432`.
- If `.env` has `DB_PORT=5433`, app container will fail to connect to DB and restart-loop.
- For Droplet deployment with compose, set `DB_PORT=5432`.

Reference files:
- `docker-compose.yml`
- `app/database.py`
- `monitoring/prometheus.yml`

## 1. Architecture You Will Deploy

DigitalOcean resources:
- 1 Ubuntu Droplet (2 vCPU / 4 GB RAM minimum recommended)
- 1 Reserved IP (recommended)
- Optional block storage volume for DB durability
- Domain DNS A record -> Droplet IP

Control Panel resource checklist (what to create right now):
- Create: `Droplets`, `Domains`, `Firewalls`
- Optional later: `Load Balancers`, `Container Registry`, `VPC Networks`
- Recommended for DB durability: `Managed Databases` (PostgreSQL)
- Do not use for this runbook: `App Platform`, `Kubernetes Clusters`

On Droplet:
- Docker containers: app, db, prometheus, alertmanager, discord-relay, grafana, caddy
- Caddy (inside Docker Compose) as reverse proxy + automatic TLS termination (Let's Encrypt)

Public endpoints:
- `https://link-shrink.duckdns.org/` -> App
- `https://link-shrink.duckdns.org/grafana` -> Grafana
- `https://link-shrink.duckdns.org/prometheus` -> Prometheus
- `https://link-shrink.duckdns.org/alertmanager` -> Alertmanager

## 2. Create and Harden Droplet

1. Create Droplet
- Ubuntu 22.04 LTS or 24.04 LTS
- Add SSH key at creation time
- Enable backups

2. Create DigitalOcean Cloud Firewall (Control Panel)
- Attach firewall to the Droplet
- Inbound allow:
    - TCP 22 from your IP only
    - TCP 80 from `0.0.0.0/0` and `::/0`
    - TCP 443 from `0.0.0.0/0` and `::/0`
- Deny all other inbound

3. SSH in and create non-root deploy user
```bash
ssh root@<DROPLET_IP>
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

4. Basic host hardening (UFW)
```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Optional but recommended:
- Disable password auth and root SSH login after key auth is verified.

Note:
- Keep both Cloud Firewall and UFW. Cloud Firewall protects at network edge; UFW protects on host.

## 3. Install Docker and Compose Plugin

Run as `deploy` user:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

## 4. Clone Repo and Prepare Environment

```bash
git clone https://github.com/<your-org-or-user>/PE-Hackathon-Template-2026.git
cd PE-Hackathon-Template-2026
cp .env.example .env
```

Edit `.env`:
```env
FLASK_DEBUG=false

DB_NAME=hackathon_db
DB_USER=postgres
DB_PASSWORD=<strong-random-password>

# Internal docker network target from app -> db
DB_HOST=db
DB_PORT=5432

# Host port mapping for db container.
# Prefer localhost-only publish for security:
DB_HOST_PORT=127.0.0.1:5432

DISCORD_WEBHOOK_URL=<optional-discord-webhook>
```

If you are using DigitalOcean Managed PostgreSQL instead of local container DB, use:
```env
DB_NAME=<managed-db-name>
DB_USER=<managed-db-user>
DB_PASSWORD=<managed-db-password>
DB_HOST=<managed-db-hostname>
DB_PORT=<managed-db-port>
```

Notes:
- Do not leave production secrets as defaults.
- If you want direct remote DB access, map `DB_HOST_PORT=5432` and lock it in firewall/IP allowlist.
- If `DISCORD_WEBHOOK_URL` is empty, alerts will be accepted by `discord-relay` and skipped with warning logs.

## 4A. Database Backups & Resilience (Required)

Problem:
- If PostgreSQL runs only as a local container on one Droplet, Droplet failure plus Docker volume corruption can permanently lose short-link data.

Fix options:
- Option 1 (recommended): Use DigitalOcean Managed PostgreSQL with automated backups + PITR.
- Option 2 (fallback): Keep local containerized PostgreSQL and run daily `pg_dump` backups to DigitalOcean Spaces (S3-compatible) using cron.

Option 1 setup checklist (Managed PostgreSQL):
1. Create a PostgreSQL managed database in the same region as the Droplet.
2. Add the Droplet/VPC as a trusted source.
3. Set app `.env` to managed `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
4. Recreate app container: `docker compose up -d --force-recreate app`.
5. Validate from app container with a simple `select 1` database check.

Option 2 setup checklist (pg_dump + Spaces + cron):
1. Create a Spaces bucket and generate Spaces access key/secret.
2. Install AWS CLI on Droplet and configure credentials.
3. Add cron job for daily dump and upload:
```bash
0 2 * * * docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > /tmp/url-shortener-$(date +\%F).sql.gz && aws s3 cp /tmp/url-shortener-$(date +\%F).sql.gz s3://<spaces-bucket>/db-backups/ && find /tmp -name 'url-shortener-*.sql.gz' -mtime +7 -delete
```
4. Test restore monthly to ensure backups are usable.

## 5. First Deployment

```bash
docker compose pull
docker compose build --pull
docker compose up -d
docker compose ps
```

Health checks:
```bash
curl -sS http://localhost:5000/health
curl -sS http://localhost:5000/metrics | head
```

Seed data (choose one):
```bash
# If CSVs are present
docker compose exec app python seed.py --users users.csv --urls urls.csv --events events.csv

# Or generate synthetic data
docker compose exec app python scripts/fake_data.py --users 50 --urls 200 --events 2000 --days 30
```

## 6. Configure Reverse Proxy & TLS (Caddy)

This project uses **Caddy** natively inside Docker Compose to handle reverse-proxying and Let's Encrypt TLS/SSL certificates automatically.

1. Ensure your DuckDNS (or other DNS) A record points to your Droplet IP.
2. Ensure ports `80` (HTTP) and `443` (HTTPS) are open in your DigitalOcean Cloud Firewall and `ufw`.
3. Update the `Caddyfile` with your domain if deploying to a different domain.
4. Caddy automatically negotiates and renews Let's Encrypt certificates when you run `docker compose up -d`.

There is no need to manually install Nginx or Certbot on the host machine!
```

## 8. Make It Survive Reboots

Docker services already have `restart: unless-stopped`, but ensure Docker starts on boot:
```bash
sudo systemctl enable docker
```

## 9. Monitoring and Alert Validation

1. Verify Prometheus targets
- Open `https://link-shrink.duckdns.org/prometheus/targets`
- Confirm `url-shortener` target is UP

2. Verify Grafana
- Open `https://link-shrink.duckdns.org/grafana`
- Default admin user: `admin`
- Password is currently set by compose env (`GF_SECURITY_ADMIN_PASSWORD`)
- Change it immediately after first login

3. Verify Alertmanager
- Open `https://link-shrink.duckdns.org/alertmanager`
- Trigger synthetic load and confirm alerts can fire
4. Verify Discord relay behavior
- Check relay logs: `docker compose logs --tail=100 discord-relay`
- Expected with webhook configured: relay logs requests and Discord receives messages
- Expected without webhook configured: relay logs `webhook_not_configured` warnings

## 10. Safe Update Procedure

```bash
cd PE-Hackathon-Template-2026
git fetch --all
git checkout main
git pull
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 app
```

Post-update smoke test:
```bash
curl -i https://link-shrink.duckdns.org/health
curl -i https://link-shrink.duckdns.org/metrics
```

Code-change compatibility checks (recommended):
```bash
# Mirrors the GitHub Actions smoke workflow locally
uv pip install --system -e .
python -m compileall app scripts run.py seed.py validate_seed.py
pytest -q
```

## 11. Rollback Procedure

If new version fails:
```bash
docker compose logs --tail=200 app
docker images
```

Pin previous image tag and restart:
```bash
# Example
docker tag <working_image_id> url-shortener:rollback
APP_IMAGE=url-shortener:rollback docker compose up -d
```

## 12. Common Failure Cases and Fixes

1. App restart-loop with DB connection refused
- For local DB mode: check `.env` has `DB_HOST=db` and `DB_PORT=5432`; confirm `db` container is healthy.
- For managed DB mode: verify `DB_HOST`, `DB_PORT`, credentials, and trusted-source network rules.

2. Certbot fails domain validation
- Confirm A record points to Droplet IP.
- Confirm ports 80 and 443 are open in UFW and cloud firewall.

3. Monitoring target down
- Check app metrics endpoint: `curl http://localhost:5000/metrics`.
- Check Prometheus config and network: `monitoring/prometheus.yml` expects `app:5000`.

4. Alerts firing but no Discord notifications
- Check `.env` has a valid `DISCORD_WEBHOOK_URL`.
- Validate relay logs: `docker compose logs --tail=200 discord-relay`.
- Confirm Alertmanager receiver posts to `http://discord-relay:8080/alert`.

## 13. Recommended Next Improvements

- If still on local DB container, migrate PostgreSQL to DigitalOcean Managed Postgres for higher durability.
- Use DigitalOcean Container Registry and pinned immutable image tags.
- Add CI/CD deployment pipeline with staged smoke checks.
- Add external uptime checks for app and Grafana.

## 14. Adopting New Upstream Changes

When pulling new code from `main`, verify these behavior-sensitive areas:

1. Monitoring and alerts stack
- Current flow is `Alertmanager -> discord-relay -> Discord webhook`.
- Ensure `discord-relay` service is running after updates:
```bash
docker compose up -d --build alertmanager discord-relay
docker compose logs --tail=100 discord-relay
```

2. App resilience changes
- `/metrics` is intentionally tolerant of temporary DB unavailability.
- Validate DB-backed routes explicitly after updates (`/urls`, `/shorten`).

3. GitHub Actions behavior
- Workflow in `.github/workflows/ci.yml` is CI smoke testing, not production deployment.
- Keep deployment as an explicit manual/ops step (or add a separate release workflow).
