<div align="center">
  <h1>🔗 Link-Shrink 🔗</h1>
  <h3>MLH PE Hackathon 2026</h3>

  <a href="https://link-shrink.duckdns.org">
    <img src="https://img.shields.io/badge/🚀_Live_Demo-https%3A%2F%2Flink--shrink.duckdns.org-2ea44f?style=for-the-badge" alt="Live Demo" />
  </a>
  <a href="https://github.com/Shreyp087/PE-Hackathon-Template-2026/actions/workflows/ci.yml">
    <img src="https://github.com/Shreyp087/PE-Hackathon-Template-2026/actions/workflows/ci.yml/badge.svg" alt="CI Smoke Tests" style="height: 28px;" />
  </a>
  <br><br>

  > **Judges / Reviewers:** 👉 **[Test the live application here](https://link-shrink.duckdns.org)** 👈

</div>

<br>

**Link-Shrink** is a production-ready URL shortener featuring **End-to-End TLS Encryption via Caddy**, built for the MLH Production Engineering Hackathon. Forked from the [PE-Hackathon-Template-2026](https://github.com/MLH-Fellowship/PE-Hackathon-Template-2026).

## How We Prove Reliability
- CI smoke tests run on every push and pull request to `main`.
- The pipeline compiles Python sources and runs endpoint-level smoke tests.
- Smoke tests verify `/health`, `/metrics`, `/system`, invalid URL handling, and JSON log formatter structure.
- Operational reliability is also validated through Prometheus + Alertmanager + Grafana + Discord relay in Docker Compose.

## Database Backups & Resilience
- Problem: If PostgreSQL runs only as a local container on a single Droplet, Droplet loss plus volume corruption can cause permanent short-link data loss.
- Fix option 1 (recommended): use DigitalOcean Managed PostgreSQL with automated backups and PITR.
- Fix option 2 (fallback): keep containerized PostgreSQL but run daily `pg_dump` backups to DigitalOcean Spaces (S3-compatible) via cron.
- Production note: document and test restore steps, not just backup creation.

## Documentation
For a complete look into our architecture, endpoints, telemetry, and operations, please see the full **[Documentation Index](docs/INDEX.md)**.

Quick start for judges and first-time reviewers: **[Jump to Demo Flow](#demo-flow-first-time-user)**.

## Overview
This service provides a fast, scalable way to shorten long URLs and redirect users seamlessly. It utilizes a Python Flask backend, Peewee ORM for database interactions, and PostgreSQL for robust data storage. The stack focuses on reliability, with a full monitoring suite ready for deployment on DigitalOcean.

## Prerequisites
- **uv**: Fast Python package manager. Install via:
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **Docker & Docker Compose**: For running the PostgreSQL database and monitoring stack.
- **Git**: For version control.

## Step-by-step Setup

### 1. Clone the Repository
```bash
git clone https://github.com/YourUsername/PE-Hackathon-Template-2026.git
cd PE-Hackathon-Template-2026
```

### 2. Configure Environment
Copy the example environment file.
```bash
cp .env.example .env
```
If you run the app locally (outside Docker), set:
- `DB_HOST=localhost`
- `DB_PORT=5432`

If you run the app with Docker Compose, set:
- `DB_HOST=db`
- `DB_PORT=5432`
- `DB_HOST_PORT=5432` (or another host port if needed)

### 3. Start Services
Start only PostgreSQL (minimal local app run):
```bash
docker compose up -d db
```

Start full observability stack (recommended for Incident Response quest):
```bash
docker compose up -d db prometheus alertmanager discord-relay grafana
```

### 4. Install Dependencies
Use `uv` to automatically create a virtual environment and install dependencies:
```bash
uv sync
```

### 5. Seed the Database
Option A: seed from CSV files (`users.csv`, `urls.csv`, `events.csv`):
```bash
uv run seed.py --users users.csv --urls urls.csv --events events.csv
```

Option B: generate synthetic data quickly:
```bash
uv run python scripts/fake_data.py --users 50 --urls 200 --events 2000 --days 30
```

### 6. Run the Server
Start the Flask application:
```bash
uv run run.py
```
The server will start locally on `http://localhost:5000`.

### 7. Verify Everything Is Up
```bash
curl http://localhost:5000/health
curl http://localhost:5000/metrics
```

If full stack is running, you can also open:
- Grafana: `https://link-shrink.duckdns.org/grafana`
- Prometheus: `https://link-shrink.duckdns.org/prometheus`
- Alertmanager: `https://link-shrink.duckdns.org/alertmanager`

## Demo Flow (First-Time User)
Use this exact flow to go from setup to testing in about 10 minutes.

### Terminal 1: Start the app
```bash
uv run run.py
```

### Terminal 2: Run a full demo sequence
1. Health + metrics checks:
```bash
curl http://localhost:5000/health
curl http://localhost:5000/system
curl http://localhost:5000/metrics
```

2. Create and test a short URL:
```bash
curl -X POST http://localhost:5000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"https://mlh.io/seasons/2026/events"}'
curl -i http://localhost:5000/r/<short_code>
```

3. Run smoke tests (fast validation):
```bash
uv run pytest -q tests/test_smoke.py
```

4. Optional: run full test suite:
```bash
uv run pytest -q
```

5. Optional incident-response demo:
```bash
uv run python scripts/watch_alerts.py
uv run python scripts/simulate.py
```

### Where to go next
- Testing and simulation details: [docs/SIMULATION.md](docs/SIMULATION.md)
- Alert triage steps: [RUNBOOK.md](RUNBOOK.md)
- API endpoint reference: [docs/API.md](docs/API.md)
- Troubleshooting common issues: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## Quick Start Example
Test the URL shortener endpoint via `curl`:
```bash
curl -X POST http://localhost:5000/shorten \
     -H "Content-Type: application/json" \
     -d '{"url":"https://mlh.io/seasons/2026/events"}'
```
Response:
```json
{
  "short_url": "http://localhost:5000/r/aB3dE"
}
```
Test the redirection:
```bash
curl -i http://localhost:5000/r/aB3dE
```
