# Architecture Decision Records (ADR)

This document formally tracks pivotal architectural choices over the trajectory of the project setup, ensuring critical historical context is systematically preserved.

---

### ADR 1: Why PostgreSQL over MySQL
- **Status**: Approved
- **Context**: The URL shortener mandates a rugged, structurally reliable relational database dedicated strictly to housing URL hashes, complex User hierarchies, and millions of read/write heavy event analytics.
- **Decision**: We aggressively selected **PostgreSQL** configured via `.env`.
- **Consequences**:
  - Unlocks robust native data-types including UUIDs, native JSONB, scaling transactional DDLs, and aggressive write-safety capabilities.
  - Generates overhead guaranteeing team understanding of python's `psycopg2` bindings.
  - Forces tuning overhead (tweaking configurations like `work_mem` securely on small Droplets to prevent mapping exhaustions).

---

### ADR 2: Why Prometheus + Grafana over a SaaS monitoring tool
- **Status**: Approved
- **Context**: The application handles high-throughput requests which immediately mandate strict health observability. Third-party SaaS metrics solutions (DataDog, New Relic) provide fantastic dashboards but inject a heavy financial cost vector.
- **Decision**: We strictly adopted the open-source **Prometheus & Grafana** observability stack mapping them directly through Docker volumes.
- **Consequences**:
  - Attains total OPEX budget isolation—telemetry runs freely on current bare metal.
  - Places fundamental operational load firmly on our team (We exclusively hold liability for balancing server TSDB disk footprints, managing Alertmanager delivery rule mapping, and generating custom Grafana PromQL displays natively).

---

### ADR 3: Why Docker Compose over bare-metal deployment
- **Status**: Approved
- **Context**: Bootstrapping Python system dependencies natively with Ubuntu OS-level C headers (typically necessary for postgres drivers) commonly provokes frustrating local-host specific ("it works on my machine") environment disparities.
- **Decision**: To containerize the ecosystem globally and boot them explicitly via **Docker and Docker Compose**.
- **Consequences**:
  - Establishes perfect parity between a developer's Windows terminal and the DigitalOcean Ubuntu cloud structures natively.
  - Slashes complex deployment cycles down to executing simple `docker compose up -d` directives.
  - Mild drawback of minor mapping performance allocations translating Docker overlay bridge internal networking traffic.

---

### ADR 4: Why a single DigitalOcean Droplet vs managed Kubernetes
- **Status**: Approved
- **Context**: Post-containerization, orchestrating images securely inside a public network mandates a cloud destination platform reliably structured to load balance traffic organically mapping out towards managed engines.
- **Decision**: Deploy infrastructure on a completely isolated **Single DigitalOcean Droplet (Virtualized Compute instance)** vs scaling out through Managed Kubernetes (DOKS).
- **Consequences**:
  - Eradicates paralyzing orchestration complexities maximizing output mapping specifically scaled for tight Hackathon MVP timelines.
  - Stabilizes budgets into rigid predictably cheap thresholds dynamically.
  - Imposes a massive single point of failure (SPOF) ceiling constraint gracefully forcing migrations natively towards robust VPC Load-Balanced Droplet arrays whenever hyper-scaling thresholds shatter MVP designs natively.
