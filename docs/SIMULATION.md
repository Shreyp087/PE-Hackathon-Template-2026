# Incident Response & Simulation Guide

This document outlines the Chaos Engineering and Load Testing suite provided in the `scripts/` directory. These scripts are strictly designed for validating the alerts listed in our [Runbook](RUNBOOK.md) and reliably demonstrating the observability of the entire stack.

---

## Scripts Overview

| Script | Core Function |
|---|---|
| `simulate.py` | The master orchestrator. Sequentially runs a 12-minute real-world incident simulation through 7 distinct phases, from background baseline traffic up to complete service failure. |
| `load_generator.py` | Simulates organic baseline user traffic (routing randomized requests to shortened URLs, `/shorten`, and `/health`) constantly running securely in the background. |
| `error_simulator.py` | Intentionally injects specific application pressure. Can seamlessly trigger `high_error_rate`, `slow_responses`, or `high_cpu` scenarios using the internal `/simulate` API testing endpoints. |
| `fake_data.py` | Synthetically seeds the PostgreSQL database instantly with thousands of realistic users, long URLs, and event tracking records. |
| `kill_service.py` | Forcefully terminates the application network routing to successfully map and trigger a primary `Service Down` alert scenario. |
| `watch_alerts.py` | A terminal-based dynamic dashboard that safely queries Prometheus and streams all active system alerts directly to your standard output securely. |

---

## How to Test and Demo
For hackathon judges or SREs actively evaluating the Prometheus alerting pipeline, you can run a fully automated end-to-end chaos test safely on your local or Droplet footprint.

### Step 1: Initialize the Live Alert Dashboard
Open an isolated terminal natively and run the alert watcher. This securely acts as your real-time incident monitor mapping directly to Prometheus:
```bash
uv run python scripts/watch_alerts.py
```

### Step 2: Trigger the Full Hackathon Simulation Engine
In a completely separate terminal window, initialize the main orchestrator natively:
```bash
uv run python scripts/simulate.py
```

### Execution Pathway
The orchestrator will automatically step meticulously through the following environments:
1. Baseline Traffic (Health Checks)
2. Sudden Traffic Spikes
3. Intense High Error Rate Injection
4. Latency / Slow Response Mapping
5. Critical CPU Mathematical Spikes
6. Total Service Outage (Kill Service)
7. Recovery and Baseline Resolution

*Observe the alerts seamlessly trigger and resolve in real-time inside your Terminal 1 Dashboard (or visually using your Grafana `http://localhost:3000` footprint)!*
