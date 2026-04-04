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
LIVE_SUMMARY_INTERVAL_SECONDS = 10


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.short_codes = []
        self.short_code_set = set()
        self.total_requests = 0
        self.success_2xx = 0
        self.redirect_3xx = 0
        self.client_error_4xx = 0
        self.server_error_5xx = 0
        self.errors = 0

    def add_short_code(self, short_code):
        if not short_code:
            return

        with self.lock:
            if short_code in self.short_code_set:
                return
            self.short_code_set.add(short_code)
            self.short_codes.append(short_code)

    def get_random_short_code(self):
        with self.lock:
            if not self.short_codes:
                return None
            return random.choice(self.short_codes)

    def record_result(self, result_key):
        with self.lock:
            self.total_requests += 1
            if result_key == "success_2xx":
                self.success_2xx += 1
            elif result_key == "redirect_3xx":
                self.redirect_3xx += 1
            elif result_key == "client_error_4xx":
                self.client_error_4xx += 1
            elif result_key == "server_error_5xx":
                self.server_error_5xx += 1
            else:
                self.errors += 1

    def summary(self, elapsed_seconds):
        with self.lock:
            return {
                "elapsed_s": round(elapsed_seconds, 2),
                "total_requests": self.total_requests,
                "success_2xx": self.success_2xx,
                "redirect_3xx": self.redirect_3xx,
                "client_error_4xx": self.client_error_4xx,
                "server_error_5xx": self.server_error_5xx,
                "errors": self.errors,
            }


REDIRECT_OPENER = urllib.request.build_opener(NoRedirectHandler())
DEFAULT_OPENER = urllib.request.build_opener()


def normalize_host(host):
    normalized = host.rstrip("/")
    if normalized.startswith("http://localhost"):
        return normalized.replace("http://localhost", "http://127.0.0.1", 1)
    if normalized.startswith("https://localhost"):
        return normalized.replace("https://localhost", "https://127.0.0.1", 1)
    return normalized


def classify_status(status_code):
    if 200 <= status_code < 300:
        return "success_2xx"
    if 300 <= status_code < 400:
        return "redirect_3xx"
    if 400 <= status_code < 500:
        return "client_error_4xx"
    if 500 <= status_code < 600:
        return "server_error_5xx"
    return "errors"


def do_request(method, url, payload=None):
    headers = {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    opener = REDIRECT_OPENER if method == "GET" else DEFAULT_OPENER

    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
            status = response.getcode()
            return status, body
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, None


def maybe_capture_short_code(state, status_code, body):
    if status_code not in (200, 201) or not body:
        return

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return

    state.add_short_code(payload.get("short_code"))


def seed_short_codes(host, state):
    for url in SEED_URLS:
        status_code, body = do_request("POST", host + "/shorten", {"url": url})
        if status_code is None:
            state.record_result("errors")
            continue

        state.record_result(classify_status(status_code))
        maybe_capture_short_code(state, status_code, body)


def pick_action():
    roll = random.random()
    if roll < 0.60:
        return "redirect"
    if roll < 0.80:
        return "shorten"
    if roll < 0.90:
        return "urls"
    if roll < 0.95:
        return "health"
    return "system"


def perform_action(host, state):
    action = pick_action()
    if action == "redirect":
        short_code = state.get_random_short_code()
        if not short_code:
            status_code, body = do_request("GET", host + "/health")
        else:
            status_code, body = do_request("GET", host + "/r/" + short_code)
    elif action == "shorten":
        status_code, body = do_request(
            "POST",
            host + "/shorten",
            {"url": random.choice(SEED_URLS)},
        )
    elif action == "urls":
        status_code, body = do_request("GET", host + "/urls")
    elif action == "health":
        status_code, body = do_request("GET", host + "/health")
    else:
        status_code, body = do_request("GET", host + "/system")

    if status_code is None:
        state.record_result("errors")
        return

    state.record_result(classify_status(status_code))
    if action == "shorten":
        maybe_capture_short_code(state, status_code, body)


def worker_loop(worker_id, host, end_time, interval_seconds, state):
    del worker_id
    next_run = time.time()

    while time.time() < end_time:
        perform_action(host, state)

        next_run += interval_seconds * random.uniform(0.85, 1.15)
        sleep_for = next_run - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_run = time.time()


def print_summary_loop(start_time, end_time, state):
    while time.time() < end_time:
        time.sleep(LIVE_SUMMARY_INTERVAL_SECONDS)
        elapsed_seconds = min(time.time() - start_time, end_time - start_time)
        print(json.dumps(state.summary(elapsed_seconds)), flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate realistic mixed traffic for the URL shortener."
    )
    parser.add_argument("--host", default="http://localhost:5000")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--rps", type=float, default=10)
    return parser.parse_args()


def main():
    args = parse_args()
    host = normalize_host(args.host)
    workers = max(1, args.workers)
    duration = max(1, args.duration)
    rps = max(0.1, args.rps)
    interval_seconds = workers / rps

    state = SharedState()
    start_time = time.time()
    end_time = start_time + duration

    seed_short_codes(host, state)

    summary_thread = threading.Thread(
        target=print_summary_loop,
        args=(start_time, end_time, state),
        daemon=True,
    )
    summary_thread.start()

    threads = []
    for worker_id in range(workers):
        thread = threading.Thread(
            target=worker_loop,
            args=(worker_id, host, end_time, interval_seconds, state),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    elapsed_seconds = time.time() - start_time
    print(json.dumps(state.summary(elapsed_seconds)), flush=True)


if __name__ == "__main__":
    main()
