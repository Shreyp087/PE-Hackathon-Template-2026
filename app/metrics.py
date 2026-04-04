import os

import psutil
from prometheus_client import Counter, Gauge, Histogram, REGISTRY

metrics_registry = REGISTRY

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
    registry=metrics_registry,
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=metrics_registry,
)

URL_REDIRECTS = Counter(
    "url_redirects_total",
    "Total number of URL redirects",
    ["short_code"],
    registry=metrics_registry,
)

URL_CREATED = Counter(
    "url_created_total",
    "Total number of shortened URLs created",
    registry=metrics_registry,
)

DB_ERRORS = Counter(
    "db_errors_total",
    "Total number of database errors",
    ["operation"],
    registry=metrics_registry,
)

ACTIVE_URLS_TOTAL = Gauge(
    "active_urls_total",
    "Current number of active shortened URLs",
    registry=metrics_registry,
)

SYSTEM_CPU_PERCENT = Gauge(
    "system_cpu_percent",
    "Current CPU utilization percentage",
    registry=metrics_registry,
)

SYSTEM_MEMORY_TOTAL_MB = Gauge(
    "system_memory_total_mb",
    "Total system memory in megabytes",
    registry=metrics_registry,
)

SYSTEM_MEMORY_USED_MB = Gauge(
    "system_memory_used_mb",
    "Used system memory in megabytes",
    registry=metrics_registry,
)

SYSTEM_MEMORY_PERCENT = Gauge(
    "system_memory_percent",
    "Current memory utilization percentage",
    registry=metrics_registry,
)

SYSTEM_DISK_PERCENT = Gauge(
    "system_disk_percent",
    "Current disk utilization percentage",
    registry=metrics_registry,
)


def refresh_system_metrics():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    snapshot = {
        "cpu_percent": round(psutil.cpu_percent(), 2),
        "memory_total_mb": round(memory.total / (1024 * 1024), 2),
        "memory_used_mb": round(memory.used / (1024 * 1024), 2),
        "memory_percent": round(memory.percent, 2),
        "disk_percent": round(disk.percent, 2),
    }

    SYSTEM_CPU_PERCENT.set(snapshot["cpu_percent"])
    SYSTEM_MEMORY_TOTAL_MB.set(snapshot["memory_total_mb"])
    SYSTEM_MEMORY_USED_MB.set(snapshot["memory_used_mb"])
    SYSTEM_MEMORY_PERCENT.set(snapshot["memory_percent"])
    SYSTEM_DISK_PERCENT.set(snapshot["disk_percent"])

    return snapshot


__all__ = [
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "URL_REDIRECTS",
    "URL_CREATED",
    "DB_ERRORS",
    "ACTIVE_URLS_TOTAL",
    "SYSTEM_CPU_PERCENT",
    "SYSTEM_MEMORY_TOTAL_MB",
    "SYSTEM_MEMORY_USED_MB",
    "SYSTEM_MEMORY_PERCENT",
    "SYSTEM_DISK_PERCENT",
    "refresh_system_metrics",
    "metrics_registry",
]
