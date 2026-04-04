# Capacity Planning & Scaling Roadmap

This document empirically identifies baseline performance factors mapping directly towards load projections detailing structural recommendations allowing smooth horizontal/vertical scaling from MVP Hackathon stages up to enterprise capacity levels.

## 1. Current Baseline Metrics 
At present natively initialized baseline (App Container + PostgreSQL DB + Prometheus/Grafana Observer footprint) scaled locally against a base **$6/mo DigitalOcean Droplet (1 vCPU, 1 GB RAM):**
- **Requests Per Second (RPS)**: Roughly ~15-20 max internally (principally stifled aggressively relying exclusively on single synchronous Python IO worker mappings via basic `run.py`).
- **DB Connections**: Peaks minimally spanning 1-5 concurrently active queries natively.
- **RAM per Component Footprint**:
  - Flask Application engine: ~50-100 MB
  - PostgreSQL Relational Database: ~100-200 MB
  - Monitoring Suite (Prometheus/Alerts/Grafana): heavily bounds ~300-400 MB actively.

## 2. Load Projections & Bottlenecks

### Tier 1: 100 Users/Day (Low Traffic / Project Startup)
- **Expected Demand**: Low frequency traffic spiking organically mapping to 1-2 API Requests Per Second natively.
- **Bottlenecks**: The 1 GB baseline physical Droplet supports this entirely seamlessly; However, heavy telemetry configurations mapping excessive historical scraping cache pools inside Prometheus may provoke memory saturation and sporadically trigger Linux kernel OOM killer actions.

### Tier 2: 10,000 Users/Day (Moderate Growth Campaign)
- **Expected Demand**: Elevated, mapping towards sustained ~10-25 Requests Per Second, peaking heavily when viral traffic flows natively into shortcode maps.
- **Bottlenecks**:
  - Natively invoking Python's default WSGI HTTP server synchronously chokes entirely processing concurrent socket mappings heavily directly under load.
  - Base Database connection pools suffer thrashing constraints significantly degrading overall network database speeds mapping locally.

### Tier 3: 1,000,000 Users/Day (High Velocity Enterprise Adoption)
- **Expected Demand**: Massive parallel connections mapping directly over 500-2,000 Requests Per Second aggressively globally hitting primary redirection points reliably.
- **Bottlenecks**:
  - A singleton centralized relational database node immediately saturates available CPU and maximum local disk-bandwidth read allocations naturally globally.
  - Networking traffic allocations reliably exhaust external interfaces natively.

## 3. Recommended Structural Scaling Roadmap

- **Vertical Scaling Upgrades (Single-Node Boost)**: Rapidly mitigating temporary growth crunches (up securely natively through to the low Stage 2 tier levels) primarily reliant on upscaling RAM.
- **Horizontal Server Topologies & Load Balancing Arrays**: Mitigating Tier 3 load environments safely requires separating the monolithic droplet model splitting applications directly mapped behind centralized intelligent DigitalOcean Cloud Load Balancer protocols managing isolated stateless App Nodes.
- **Database Read Replica Pooling Mechanisms**: The underlying `/shorten` service architecture operates on a drastic 99:1 read-to-write imbalance structurally. Implementing PostgreSQL asynchronous read-only cluster pools isolates destructive locking anomalies natively mapping heavily scaling `/redirect` velocity.
- **Redis Internal Distributed Cache Storage**: Augment internal database loads substantially structuring isolated low-latency `REDIS_URL` memory layers safely shielding massive global duplicate code lookups reliably mapping responses instantly offline.

## 4. Hardware Sizing & Topology Guide Matrix

| Traffic Tier | Base RPS | Est. Target DB Connections | Hardware RAM Requirement | Recommended Topology Hardware Setup Formulations |
|--------------|----------|----------------------------|--------------------------|--------------------------------------------------|
| **100/day**  | `< 2` | `5` | `1 GB Overall` | Single Base DO Droplet (1 vCPU / 1GB RAM) locally running standard docker-compose globally. |
| **10K/day**  | `10-25` | `20-50` | `2-4 GB Overall` | Upgraded scale DO VM (2 vCPU / 4GB RAM) safely mapping `gunicorn` parallel WSGI workers coupled natively against a PgBouncer connection multiplex layer. |
| **1M/day**   | `1,000+` | `300+` | `16GB+ Splintered` | Dedicated Database DbaaS (DigitalOcean Managed App) horizontally matched against an external Load Balancer feeding directly towards a massive structured subnet (3-5 App distinct nodes) insulated via Redis caching memory. |
