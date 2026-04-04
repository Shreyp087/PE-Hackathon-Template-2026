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


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LoadGenerator:
    def __init__(self, host, workers, duration, rps):
        self.host = host.rstrip("/")
        self.workers = max(1, workers)
        self.duration = max(1, duration)
        self.rps = max(0.0, float(rps))
        self.per_worker_interval = (float(self.workers) / self.rps) if self.rps > 0 else 0.0

        self.start_time = None
        self.stop_event = threading.Event()
        self.stats_lock = threading.Lock()
        self.codes_lock = threading.Lock()

        self.short_codes = []
        self.stats = {
            "total_requests": 0,
            "success_2xx": 0,
            "redirect_3xx": 0,
            "client_error_4xx": 0,
            "server_error_5xx": 0,
            "errors": 0,
        }

        self.default_opener = urllib.request.build_opener()
        self.no_redirect_opener = urllib.request.build_opener(NoRedirectHandler())

    def _elapsed_seconds(self):
        if self.start_time is None:
            return 0.0
        return round(time.monotonic() - self.start_time, 2)

    def _summary(self):
        with self.stats_lock:
            summary = dict(self.stats)
        summary["elapsed_s"] = self._elapsed_seconds()
        return summary

    def _record_status(self, status_code):
        with self.stats_lock:
            self.stats["total_requests"] += 1
            if 200 <= status_code < 300:
                self.stats["success_2xx"] += 1
            elif 300 <= status_code < 400:
                self.stats["redirect_3xx"] += 1
            elif 400 <= status_code < 500:
                self.stats["client_error_4xx"] += 1
            elif 500 <= status_code < 600:
                self.stats["server_error_5xx"] += 1

    def _record_error(self):
        with self.stats_lock:
            self.stats["total_requests"] += 1
            self.stats["errors"] += 1

    def _request(self, method, path, payload=None, follow_redirects=True):
        url = self.host + path
        headers = {}
        data = None

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        opener = self.default_opener if follow_redirects else self.no_redirect_opener

        try:
            with opener.open(req, timeout=5) as response:
                status = getattr(response, "status", response.getcode())
                body = response.read()
                self._record_status(status)
                return status, body
        except urllib.error.HTTPError as exc:
            self._record_status(exc.code)
            body = b""
            try:
                body = exc.read()
            except Exception:
                body = b""
            return exc.code, body
        except (urllib.error.URLError, TimeoutError, OSError):
            self._record_error()
            return None, None

    def _extract_short_code(self, body):
        if not body:
            return None

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        if isinstance(payload, dict):
            for key in ("short_code", "shortCode", "code"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value

            nested = payload.get("data")
            if isinstance(nested, dict):
                for key in ("short_code", "shortCode", "code"):
                    value = nested.get(key)
                    if isinstance(value, str) and value:
                        return value

        return None

    def seed_short_codes(self):
        for url in SEED_URLS:
            status, body = self._request("POST", "/shorten", {"url": url})
            if status is None:
                continue

            short_code = self._extract_short_code(body)
            if short_code:
                with self.codes_lock:
                    self.short_codes.append(short_code)

    def _random_short_code(self):
        with self.codes_lock:
            if not self.short_codes:
                return None
            return random.choice(self.short_codes)

    def _store_short_code_from_response(self, body):
        short_code = self._extract_short_code(body)
        if short_code:
            with self.codes_lock:
                self.short_codes.append(short_code)

    def _do_redirect(self):
        short_code = self._random_short_code()
        if not short_code:
            self._do_shorten()
            return
        self._request("GET", "/r/" + short_code, follow_redirects=False)

    def _do_shorten(self):
        url = random.choice(SEED_URLS)
        status, body = self._request("POST", "/shorten", {"url": url})
        if status is not None and 200 <= status < 300:
            self._store_short_code_from_response(body)

    def _do_list_urls(self):
        self._request("GET", "/urls")

    def _do_health(self):
        self._request("GET", "/health")

    def _do_system(self):
        self._request("GET", "/system")

    def _choose_action(self):
        roll = random.random()
        if roll < 0.60:
            return self._do_redirect
        if roll < 0.80:
            return self._do_shorten
        if roll < 0.90:
            return self._do_list_urls
        if roll < 0.95:
            return self._do_health
        return self._do_system

    def worker(self):
        next_run = time.monotonic()

        while not self.stop_event.is_set():
            now = time.monotonic()
            if now >= self.start_time + self.duration:
                self.stop_event.set()
                break

            if self.per_worker_interval > 0 and now < next_run:
                time.sleep(min(next_run - now, 0.1))
                continue

            action = self._choose_action()
            action()

            if self.per_worker_interval > 0:
                next_run += self.per_worker_interval
                if next_run < time.monotonic():
                    next_run = time.monotonic()

    def reporter(self):
        while not self.stop_event.wait(10):
            print(json.dumps(self._summary()))

    def run(self):
        self.start_time = time.monotonic()
        self.seed_short_codes()

        reporter_thread = threading.Thread(target=self.reporter, daemon=True)
        reporter_thread.start()

        workers = []
        for _ in range(self.workers):
            thread = threading.Thread(target=self.worker, daemon=True)
            thread.start()
            workers.append(thread)

        for thread in workers:
            thread.join()

        self.stop_event.set()
        reporter_thread.join(timeout=1)
        print(json.dumps(self._summary()))


def parse_args():
    parser = argparse.ArgumentParser(description="Traffic simulator for the URL shortener service.")
    parser.add_argument("--host", default="http://localhost:5000", help="Base URL for the service.")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent worker threads.")
    parser.add_argument("--duration", type=int, default=300, help="How long to run, in seconds.")
    parser.add_argument("--rps", type=float, default=10, help="Target requests per second across all workers.")
    return parser.parse_args()


def main():
    args = parse_args()
    generator = LoadGenerator(
        host=args.host,
        workers=args.workers,
        duration=args.duration,
        rps=args.rps,
    )
    generator.run()


if __name__ == "__main__":
    main()
