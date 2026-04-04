import argparse
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a full realistic incident simulation for the URL shortener."
    )
    parser.add_argument("--host", default="http://localhost:5000")
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument(
        "--discord",
        dest="discord",
        action="store_true",
        help="Print reminders to check Discord notifications.",
    )
    parser.add_argument(
        "--no-discord",
        dest="discord",
        action="store_false",
        help="Disable Discord reminder messages.",
    )
    parser.set_defaults(discord=True)
    return parser.parse_args()


def phase_banner(title):
    line = "=" * 72
    print()
    print(line, flush=True)
    print(title, flush=True)
    print(line, flush=True)


def normalize_url(url):
    raw = url.strip()
    if "://" not in raw:
        raw = "http://" + raw

    parsed = urlsplit(raw)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc
    path = parsed.path

    # Recover from inputs like http://1.2.3.4/:9090
    if netloc and path.startswith("/:") and path.count("/") == 1:
        netloc = f"{netloc}:{path[2:]}"
        path = ""

    reparsed = urlsplit(urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment)))
    hostname = reparsed.hostname or ""
    port = reparsed.port

    if hostname in {"localhost", "::1"}:
        hostname = "127.0.0.1"

    if ":" in hostname and not hostname.startswith("["):
        host_part = f"[{hostname}]"
    else:
        host_part = hostname

    normalized_netloc = host_part + (f":{port}" if port else "")
    normalized_path = reparsed.path.rstrip("/")
    if normalized_path == "/":
        normalized_path = ""

    return urlunsplit(
        (
            reparsed.scheme or "http",
            normalized_netloc,
            normalized_path,
            reparsed.query,
            reparsed.fragment,
        )
    )


def is_local_target(url):
    parsed = urlsplit(url)
    return (parsed.hostname or "") in LOCAL_HOSTS


def with_port(url, port):
    parsed = urlsplit(url)
    hostname = parsed.hostname or "127.0.0.1"

    if ":" in hostname and not hostname.startswith("["):
        host_part = f"[{hostname}]"
    else:
        host_part = hostname

    return urlunsplit((parsed.scheme or "http", f"{host_part}:{port}", "", "", ""))


def launch_background(command):
    print("Launching:", " ".join(command), flush=True)
    return subprocess.Popen(command)


def run_blocking(command):
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def wait_for_background(process, label):
    timed_out = False
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        timed_out = True
        print(f"{label} is still running after its phase window. Terminating it.", flush=True)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"{label} did not exit cleanly. Killing it.", flush=True)
            process.kill()
            process.wait(timeout=5)

    if timed_out:
        return

    if process.returncode not in (0, None):
        raise subprocess.CalledProcessError(process.returncode, process.args)


def sleep_with_progress(seconds):
    time.sleep(seconds)


def terminate_all(processes):
    for label, process in processes:
        if process.poll() is not None:
            continue
        print(f"Stopping background process: {label}", flush=True)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def alertmanager_url_from_prometheus(prometheus_url):
    return with_port(prometheus_url, 9093)


def main():
    args = parse_args()
    started_at = time.time()
    active_processes = []
    python = sys.executable
    host = normalize_url(args.host)
    prometheus = normalize_url(args.prometheus)
    local_target = is_local_target(host)
    alertmanager = alertmanager_url_from_prometheus(prometheus)
    grafana = with_port(prometheus, 3000)

    if host != args.host.rstrip("/"):
        print(
            f"Using {host} instead of {args.host.rstrip('/')} for local reliability on this machine.",
            flush=True,
        )
    if prometheus != args.prometheus.rstrip("/"):
        print(
            f"Using {prometheus} instead of {args.prometheus.rstrip('/')} for local reliability on this machine.",
            flush=True,
        )

    try:
        if local_target:
            phase_banner("PHASE 0 - Seed fake data")
            run_blocking(
                [
                    python,
                    "scripts/fake_data.py",
                    "--users",
                    "50",
                    "--urls",
                    "200",
                    "--events",
                    "2000",
                ]
            )
        else:
            phase_banner("PHASE 0 - Remote HTTP seed")
            print(
                "Remote target detected - skipping direct DB seeding and priming data through the public API instead",
                flush=True,
            )
            run_blocking(
                [
                    python,
                    "scripts/load_generator.py",
                    "--host",
                    host,
                    "--workers",
                    "1",
                    "--duration",
                    "5",
                    "--rps",
                    "1",
                ]
            )

        phase_banner("PHASE 1 - Baseline traffic")
        baseline = launch_background(
            [
                python,
                "scripts/load_generator.py",
                "--host",
                host,
                "--duration",
                "60",
                "--rps",
                "5",
            ]
        )
        active_processes.append(("baseline traffic", baseline))
        print("Baseline traffic running - watch Grafana Request Rate panel", flush=True)
        sleep_with_progress(60)
        wait_for_background(baseline, "Baseline traffic")
        active_processes.remove(("baseline traffic", baseline))

        phase_banner("PHASE 2 - Traffic spike")
        spike = launch_background(
            [
                python,
                "scripts/error_simulator.py",
                "--host",
                host,
                "--scenario",
                "spike",
                "--duration",
                "60",
            ]
        )
        active_processes.append(("traffic spike", spike))
        print("SPIKE started - watch Request Rate panel spike", flush=True)
        sleep_with_progress(60)
        wait_for_background(spike, "Traffic spike")
        active_processes.remove(("traffic spike", spike))

        phase_banner("PHASE 3 - High error rate")
        high_error = launch_background(
            [
                python,
                "scripts/error_simulator.py",
                "--host",
                host,
                "--scenario",
                "high_error_rate",
                "--duration",
                "90",
            ]
        )
        active_processes.append(("high error injection", high_error))
        print(
            "ERROR INJECTION started - HighErrorRate alert should fire within 2 minutes",
            flush=True,
        )
        sleep_with_progress(90)
        wait_for_background(high_error, "High error injection")
        active_processes.remove(("high error injection", high_error))

        phase_banner("PHASE 4 - Slow responses")
        slow = launch_background(
            [
                python,
                "scripts/error_simulator.py",
                "--host",
                host,
                "--scenario",
                "slow_responses",
                "--duration",
                "180",
            ]
        )
        active_processes.append(("slow response injection", slow))
        print(
            "SLOW RESPONSE INJECTION started - SlowResponseTime alert should fire within about 3 minutes",
            flush=True,
        )
        sleep_with_progress(180)
        wait_for_background(slow, "Slow response injection")
        active_processes.remove(("slow response injection", slow))

        phase_banner("PHASE 5 - High CPU")
        high_cpu = launch_background(
            [
                python,
                "scripts/error_simulator.py",
                "--host",
                host,
                "--scenario",
                "high_cpu",
                "--duration",
                "300",
            ]
        )
        active_processes.append(("high cpu injection", high_cpu))
        print(
            "HIGH CPU INJECTION started - HighCPU alert should fire after the 2m rate window and 2m hold time",
            flush=True,
        )
        sleep_with_progress(300)
        wait_for_background(high_cpu, "High CPU injection")
        active_processes.remove(("high cpu injection", high_cpu))

        phase_banner("PHASE 6 - Service kill")
        if local_target:
            print("SERVICE KILLED - ServiceDown alert should fire within 1 minute", flush=True)
            if args.discord:
                print("Check Discord for notification", flush=True)
            run_blocking(
                [
                    python,
                    "scripts/kill_service.py",
                    "--host",
                    host,
                    "--down-time",
                    "90",
                ]
            )
        else:
            print(
                "Remote target detected - skipping kill_service because it only stops a local Docker container",
                flush=True,
            )
            if args.discord:
                print(
                    "To trigger ServiceDown on the deployed host, stop the app container on the droplet for at least 60 seconds",
                    flush=True,
                )

        phase_banner("PHASE 7 - Recovery baseline")
        recovery = launch_background(
            [
                python,
                "scripts/load_generator.py",
                "--host",
                host,
                "--duration",
                "60",
                "--rps",
                "3",
            ]
        )
        active_processes.append(("recovery traffic", recovery))
        print("Recovery traffic - watch alerts resolve in Alertmanager", flush=True)
        sleep_with_progress(60)
        wait_for_background(recovery, "Recovery traffic")
        active_processes.remove(("recovery traffic", recovery))

    except KeyboardInterrupt:
        print("\nSimulation interrupted. Cleaning up background processes...", flush=True)
        terminate_all(active_processes)
        raise SystemExit(130)
    finally:
        terminate_all(active_processes)

    total_runtime = int(time.time() - started_at)
    phase_banner("PHASE END - Summary")
    print(f"Simulation complete. Total runtime: {total_runtime}s", flush=True)
    print(f"Open Grafana at {grafana} - admin / hackathon2026", flush=True)
    print(f"Open Prometheus at {prometheus}/alerts", flush=True)
    print(f"Open Alertmanager at {alertmanager}", flush=True)
    if args.discord:
        print(
            "Check Discord for: HighErrorRate + SlowResponseTime + HighCPU alerts and, if tested locally or manually on the droplet, ServiceDown + resolved notifications",
            flush=True,
        )
    print(
        "For judge demo: run python scripts/watch_alerts.py to show live terminal dashboard",
        flush=True,
    )


if __name__ == "__main__":
    main()
