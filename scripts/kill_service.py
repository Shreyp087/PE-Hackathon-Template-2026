import argparse
import http.client
import subprocess
import time
import urllib.error
import urllib.request


def parse_args():
    parser = argparse.ArgumentParser(
        description="Simulate a complete service outage to trigger the ServiceDown alert."
    )
    parser.add_argument("--container", default="pe-hackathon-template-2026-app-1")
    parser.add_argument("--down-time", type=int, default=90)
    parser.add_argument("--host", default="http://127.0.0.1:5000")
    return parser.parse_args()


def normalize_host(host):
    normalized = host.rstrip("/")
    if normalized.startswith("http://localhost"):
        return normalized.replace("http://localhost", "http://127.0.0.1", 1)
    if normalized.startswith("https://localhost"):
        return normalized.replace("https://localhost", "https://127.0.0.1", 1)
    return normalized


def timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def health_status(host):
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/health", timeout=5) as response:
            return response.getcode()
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, OSError):
        return None


def poll_down(host, down_started_at, down_time):
    while True:
        elapsed = time.time() - down_started_at
        if elapsed >= down_time:
            break

        status = health_status(host)
        if status != 200:
            print(
                f"[{timestamp()}] SERVICE DOWN - elapsed {int(elapsed)}s - Prometheus alert should fire within 60s",
                flush=True,
            )
        else:
            print(f"[{timestamp()}] Health check status: 200", flush=True)
        time.sleep(5)


def poll_restore(host, down_started_at):
    while True:
        status = health_status(host)
        if status == 200:
            total_downtime = int(time.time() - down_started_at)
            print(
                f"[{timestamp()}] SERVICE RESTORED - total downtime: {total_downtime}s - check Discord for alert + resolved notifications",
                flush=True,
            )
            return

        print(f"[{timestamp()}] Waiting for service to recover... health status: {status}", flush=True)
        time.sleep(3)


def main():
    args = parse_args()
    container_name = args.container
    down_time = max(1, args.down_time)
    host = normalize_host(args.host)

    print("Killing service in 3... 2... 1...", flush=True)
    time.sleep(3)

    print(f"[{timestamp()}] KILLING SERVICE", flush=True)
    stop_result = subprocess.run(["docker", "stop", container_name], check=False)
    if stop_result.returncode != 0:
        raise SystemExit(stop_result.returncode)

    down_started_at = time.time()
    poll_down(host, down_started_at, down_time)

    start_result = subprocess.run(["docker", "start", container_name], check=False)
    if start_result.returncode != 0:
        raise SystemExit(start_result.returncode)

    poll_restore(host, down_started_at)


if __name__ == "__main__":
    main()
