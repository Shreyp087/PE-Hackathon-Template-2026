# URL Shortener — MLH PE Hackathon 2026

A production-ready URL shortener built for the MLH Production Engineering Hackathon. Forked from the [PE-Hackathon-Template-2026](https://github.com/MLH-Fellowship/PE-Hackathon-Template-2026).

## Documentation
For a complete look into our architecture, endpoints, telemetry, and operations, please see the full **[Documentation Index](INDEX.md)**.

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
Ensure that `DB_HOST=localhost` if you are running the app locally outside of Docker.

### 3. Start PostgreSQL Database
We provide a `docker-compose.yml` to easily spin up the required database and monitoring stack:
```bash
docker compose up -d db
```

### 4. Install Dependencies
Use `uv` to automatically create a virtual environment and install dependencies:
```bash
uv sync
```

### 5. Seed the Database
To initialize the schema and populate the database with dummy data, use the provided CSV files (`users.csv`, `urls.csv`, `events.csv`). Run your setup or seed script (the exact file name may vary, e.g., `seed.py` or manually via python shell):
```bash
uv run seed.py --users users.csv --urls urls.csv --events events.csv
```

### 6. Run the Server
Start the Flask application:
```bash
uv run run.py
```
The server will start locally on `http://localhost:5000`.

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
