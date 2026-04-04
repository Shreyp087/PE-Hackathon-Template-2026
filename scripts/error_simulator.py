import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request


SEED_URLS = [
    "https://github.com",
    "https://google.com",
    "https://stackoverflow.com",
    "https://python.org",
    "https://flask.palletsprojects.com",
    "https://prometheus.io",
    "https://grafana.com",
    "https://digitalocean.com",
    "https://discord.com",
    "https://mlh.io",
    "https://news.ycombinator.com",
    "https://reddit.com/r/python",
    "https://fastapi.tiangolo.com",
    "https://docker.com",
    "https://postgresql.org",
    "https://nginx.org",
    "https://cloudflare.com",
    "https://github.com/features/actions",
    "https://peewee-orm.com",
    "https://gunicorn.org",
]

REQUEST_TIMEOUT_SECONDS = 10


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


REDIRECT_OPENER = urllib.request.build_opener(NoRedirectHandler())
DEFAULT_OPENER = urllib.request.build_opener()


class SharedCodes:
    def __init__(self):
        self.lock = threading.Lock()
        self.short_codes = []
        self.short_code_set = set()

    def add(self, short_code):
        if not short_code:
            return

        with self.lock:
            if short_code in self.short_code_set:
                return
            self.short_code_set.add(short_code)
            self.short_codes.append(short_code)

    def random_code(self):
        with self.lock:
            if not self.short_codes:
                return None
            return random.choice(self.short_codes)

    def count(self):
        with self.lock:
            return len(self.short_codes)


def normalize_host(host):
    normalized = host.rstrip("/")
    if normalized.startswith("http://localhost"):
        return normalized.replace("http://localhost", "http://127.0.0.1", 1)
    if normalized.startswith("https://localhost"):
        return normalized.replace("https://localhost", "https://127.0.0.1", 1)
    return normalized


def percentile(values, pct):
    if not values:
        return 0.0

    ordered = sorted(values)
    index = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def classify_status(status_code):
    if status_code is None:
        return "errors"
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "errors"


def request_url(method, url, payload=None, raw_body=None, headers=None):
    request_headers = dict(headers or {})
    data = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    elif raw_body is not None:
        data = raw_body

    request = urllib.request.Request(
        url=url,
        data=data,
        headers=request_headers,
        method=method,
    )
    opener = REDIRECT_OPENER if method == "GET" else DEFAULT_OPENER

    started = time.perf_counter()
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
            status_code = response.getcode()
            latency_ms = (time.perf_counter() - started) * 1000.0
            return status_code, body, latency_ms
    except urllib.error.HTTPError as exc:
        body = exc.read()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return exc.code, body, latency_ms
    except (urllib.error.URLError, TimeoutError, OSError):
        latency_ms = (time.perf_counter() - started) * 1000.0
        return None, None, latency_ms


def capture_short_code(shared_codes, status_code, body):
    if status_code not in (200, 201) or not body:
        return

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return

    shared_codes.add(payload.get("short_code"))


def seed_short_codes(host, shared_codes):
    for url in SEED_URLS:
        status_code, body, _ = request_url("POST", host + "/shorten", payload={"url": url})
        capture_short_code(shared_codes, status_code, body)

    print(
        json.dumps(
            {
                "event": "seed_complete",
                "seeded_short_codes": shared_codes.count(),
            }
        ),
        flush=True,
    )


def run_high_error_rate(host, duration_seconds):
    started = time.time()
    end_time = started + duration_seconds
    last_report = started
    total_4xx = 0
    total_5xx = 0
    total_errors = 0
    iteration = 0
    interval_seconds = 1.0 / 20.0

    print(
        json.dumps(
            {
                "event": "scenario_start",
                "scenario": "high_error_rate",
                "duration_s": duration_seconds,
                "target_rps": 20,
            }
        ),
        flush=True,
    )

    next_run = time.time()
    while time.time() < end_time:
        mode = iteration % 3
        if mode == 0:
            status_code, _, _ = request_url(
                "POST",
                host + "/shorten",
                payload={"url": "not-a-valid-url"},
            )
        elif mode == 1:
            status_code, _, _ = request_url(
                "GET",
                host + "/r/NOTFOUND" + str(iteration),
            )
        else:
            status_code, _, _ = request_url(
                "POST",
                host + "/shorten",
                payload={},
            )

        result = classify_status(status_code)
        if result == "4xx":
            total_4xx += 1
        elif result == "5xx":
            total_5xx += 1
        elif result == "errors":
            total_errors += 1

        now = time.time()
        if now - last_report >= 5:
            print(
                json.dumps(
                    {
                        "scenario": "high_error_rate",
                        "elapsed_s": round(now - started, 2),
                        "responses_4xx": total_4xx,
                        "responses_5xx": total_5xx,
                        "errors": total_errors,
                    }
                ),
                flush=True,
            )
            last_report = now

        iteration += 1
        next_run += interval_seconds
        sleep_for = next_run - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_run = time.time()

    print(
        json.dumps(
            {
                "event": "scenario_complete",
                "scenario": "high_error_rate",
                "elapsed_s": round(time.time() - started, 2),
                "responses_4xx": total_4xx,
                "responses_5xx": total_5xx,
                "errors": total_errors,
            }
        ),
        flush=True,
    )


def run_slow_responses(host, duration_seconds):
    started = time.time()
    end_time = started + duration_seconds
    last_report = started
    latency_state = {
        "lock": threading.Lock(),
        "latencies_ms": [],
        "errors": 0,
        "requests": 0,
    }
    start_event = threading.Event()
    worker_count = 1

    print(
        json.dumps(
            {
                "event": "scenario_start",
                "scenario": "slow_responses",
                "duration_s": duration_seconds,
                "threads": worker_count,
            }
        ),
        flush=True,
    )

    def worker():
        start_event.wait()
        while time.time() < end_time:
            status_code, _, latency_ms = request_url(
                "GET",
                host + "/simulate/slow?seconds=1.6",
            )
            with latency_state["lock"]:
                latency_state["latencies_ms"].append(latency_ms)
                latency_state["requests"] += 1
                if classify_status(status_code) in ("5xx", "errors"):
                    latency_state["errors"] += 1

    for _ in range(worker_count):
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    start_event.set()

    while time.time() < end_time:
        time.sleep(1)
        now = time.time()
        if now - last_report < 10:
            continue

        with latency_state["lock"]:
            window = list(latency_state["latencies_ms"])
            latency_state["latencies_ms"].clear()
            total_requests = latency_state["requests"]
            errors = latency_state["errors"]

        print(
            json.dumps(
                {
                    "scenario": "slow_responses",
                    "elapsed_s": round(now - started, 2),
                    "samples": len(window),
                    "p50_latency_ms": round(percentile(window, 50), 2),
                    "p95_latency_ms": round(percentile(window, 95), 2),
                    "requests": total_requests,
                    "errors": errors,
                }
            ),
            flush=True,
        )
        last_report = now

    with latency_state["lock"]:
        window = list(latency_state["latencies_ms"])
        total_requests = latency_state["requests"]
        errors = latency_state["errors"]

    print(
        json.dumps(
            {
                "event": "scenario_complete",
                "scenario": "slow_responses",
                "elapsed_s": round(time.time() - started, 2),
                "samples": len(window),
                "p50_latency_ms": round(percentile(window, 50), 2),
                "p95_latency_ms": round(percentile(window, 95), 2),
                "requests": total_requests,
                "errors": errors,
            }
        ),
        flush=True,
    )


def run_high_cpu(host, duration_seconds):
    started = time.time()
    end_time = started + duration_seconds
    last_report = started
    worker_count = 1
    request_state = {
        "lock": threading.Lock(),
        "requests": 0,
        "errors": 0,
        "latencies_ms": [],
    }
    start_event = threading.Event()

    print(
        json.dumps(
            {
                "event": "scenario_start",
                "scenario": "high_cpu",
                "duration_s": duration_seconds,
                "threads": worker_count,
            }
        ),
        flush=True,
    )

    def worker():
        start_event.wait()
        while time.time() < end_time:
            status_code, _, latency_ms = request_url(
                "GET",
                host + "/simulate/cpu?seconds=1.5",
            )
            with request_state["lock"]:
                request_state["requests"] += 1
                request_state["latencies_ms"].append(latency_ms)
                if classify_status(status_code) in ("5xx", "errors"):
                    request_state["errors"] += 1

    for _ in range(worker_count):
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    start_event.set()

    while time.time() < end_time:
        time.sleep(1)
        now = time.time()
        if now - last_report < 5:
            continue

        with request_state["lock"]:
            window = list(request_state["latencies_ms"])
            request_state["latencies_ms"].clear()
            total_requests = request_state["requests"]
            errors = request_state["errors"]

        print(
            json.dumps(
                {
                    "scenario": "high_cpu",
                    "elapsed_s": round(now - started, 2),
                    "requests": total_requests,
                    "errors": errors,
                    "p50_latency_ms": round(percentile(window, 50), 2),
                    "p95_latency_ms": round(percentile(window, 95), 2),
                }
            ),
            flush=True,
        )
        last_report = now

    with request_state["lock"]:
        window = list(request_state["latencies_ms"])
        total_requests = request_state["requests"]
        errors = request_state["errors"]

    print(
        json.dumps(
            {
                "event": "scenario_complete",
                "scenario": "high_cpu",
                "elapsed_s": round(time.time() - started, 2),
                "requests": total_requests,
                "errors": errors,
                "p50_latency_ms": round(percentile(window, 50), 2),
                "p95_latency_ms": round(percentile(window, 95), 2),
            }
        ),
        flush=True,
    )


def spike_phase(elapsed_seconds, duration_seconds):
    phase_one_end = duration_seconds * 0.25
    phase_two_end = duration_seconds * 0.75

    if elapsed_seconds < phase_one_end:
        return "baseline", 2.0
    if elapsed_seconds < phase_two_end:
        ramp_progress = (elapsed_seconds - phase_one_end) / max(
            phase_two_end - phase_one_end, 1.0
        )
        return "spike", 2.0 + (98.0 * ramp_progress)
    return "recovery", 2.0


def run_spike(host, duration_seconds, shared_codes):
    started = time.time()
    end_time = started + duration_seconds
    last_report = started
    request_state = {
        "lock": threading.Lock(),
        "requests": 0,
        "errors": 0,
    }
    worker_count = 10

    print(
        json.dumps(
            {
                "event": "scenario_start",
                "scenario": "spike",
                "duration_s": duration_seconds,
                "workers": worker_count,
            }
        ),
        flush=True,
    )

    def spike_worker():
        next_run = time.time()
        while time.time() < end_time:
            if random.random() < 0.65 and shared_codes.count() > 0:
                short_code = shared_codes.random_code()
                status_code, _, _ = request_url("GET", host + "/r/" + short_code)
            else:
                status_code, body, _ = request_url(
                    "POST",
                    host + "/shorten",
                    payload={"url": random.choice(SEED_URLS)},
                )
                capture_short_code(shared_codes, status_code, body)

            with request_state["lock"]:
                request_state["requests"] += 1
                if classify_status(status_code) in ("5xx", "errors"):
                    request_state["errors"] += 1

            elapsed_seconds = time.time() - started
            _, current_rps = spike_phase(elapsed_seconds, duration_seconds)
            per_worker_interval = worker_count / max(current_rps, 0.1)
            next_run += per_worker_interval
            sleep_for = next_run - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_run = time.time()

    threads = []
    for _ in range(worker_count):
        thread = threading.Thread(target=spike_worker, daemon=True)
        thread.start()
        threads.append(thread)

    while time.time() < end_time:
        time.sleep(1)
        now = time.time()
        if now - last_report < 5:
            continue

        elapsed_seconds = now - started
        phase_name, current_rps = spike_phase(elapsed_seconds, duration_seconds)
        with request_state["lock"]:
            total_requests = request_state["requests"]
            errors = request_state["errors"]

        print(
            json.dumps(
                {
                    "scenario": "spike",
                    "elapsed_s": round(elapsed_seconds, 2),
                    "phase": phase_name,
                    "target_rps": round(current_rps, 2),
                    "requests": total_requests,
                    "errors": errors,
                }
            ),
            flush=True,
        )
        last_report = now

    for thread in threads:
        thread.join()

    elapsed_seconds = time.time() - started
    phase_name, current_rps = spike_phase(elapsed_seconds, duration_seconds)
    with request_state["lock"]:
        total_requests = request_state["requests"]
        errors = request_state["errors"]

    print(
        json.dumps(
            {
                "event": "scenario_complete",
                "scenario": "spike",
                "elapsed_s": round(elapsed_seconds, 2),
                "phase": phase_name,
                "target_rps": round(current_rps, 2),
                "requests": total_requests,
                "errors": errors,
            }
        ),
        flush=True,
    )


def run_cascade(host, duration_seconds, shared_codes):
    print(
        json.dumps(
            {
                "event": "scenario_start",
                "scenario": "cascade",
                "duration_s": duration_seconds,
            }
        ),
        flush=True,
    )

    remaining = duration_seconds

    def transition(step_name, step_duration):
        print(
            json.dumps(
                {
                    "event": "cascade_step",
                    "step": step_name,
                    "duration_s": step_duration,
                    "remaining_s_before_step": remaining,
                }
            ),
            flush=True,
        )

    run_for = min(30, remaining)
    if run_for > 0:
        transition("high_error_rate", run_for)
        run_high_error_rate(host, run_for)
        remaining -= run_for

    sleep_for = min(10, remaining)
    if sleep_for > 0:
        transition("sleep_after_high_error_rate", sleep_for)
        time.sleep(sleep_for)
        remaining -= sleep_for

    run_for = min(30, remaining)
    if run_for > 0:
        transition("slow_responses", run_for)
        run_slow_responses(host, run_for)
        remaining -= run_for

    sleep_for = min(10, remaining)
    if sleep_for > 0:
        transition("sleep_after_slow_responses", sleep_for)
        time.sleep(sleep_for)
        remaining -= sleep_for

    if remaining > 0:
        transition("spike", remaining)
        run_spike(host, remaining, shared_codes)
        remaining = 0

    print(
        json.dumps(
            {
                "event": "scenario_complete",
                "scenario": "cascade",
                "elapsed_s": duration_seconds,
                "remaining_s": remaining,
            }
        ),
        flush=True,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Simulate targeted failure conditions for Prometheus alerts."
    )
    parser.add_argument("--host", default="http://127.0.0.1:5000")
    parser.add_argument(
        "--scenario",
        choices=[
            "high_error_rate",
            "slow_responses",
            "high_cpu",
            "spike",
            "cascade",
            "all",
        ],
        required=True,
    )
    parser.add_argument("--duration", type=int, default=120)
    return parser.parse_args()


def main():
    args = parse_args()
    host = normalize_host(args.host)
    duration_seconds = max(1, args.duration)
    shared_codes = SharedCodes()

    seed_short_codes(host, shared_codes)

    scenario = args.scenario
    if scenario == "high_error_rate":
        run_high_error_rate(host, duration_seconds)
    elif scenario == "slow_responses":
        run_slow_responses(host, duration_seconds)
    elif scenario == "high_cpu":
        run_high_cpu(host, duration_seconds)
    elif scenario == "spike":
        run_spike(host, duration_seconds, shared_codes)
    else:
        run_cascade(host, duration_seconds, shared_codes)


if __name__ == "__main__":
    main()
