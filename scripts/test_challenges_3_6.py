import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

from werkzeug.serving import make_server

from app import create_app

HOST = "127.0.0.1"
PORT = 5055
BASE = f"http://{HOST}:{PORT}"


def req(method, path, body=None, expected_status=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    request_obj = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(request_obj) as response:
            payload = response.read()
            parsed = json.loads(payload) if payload else None
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        parsed = json.loads(payload) if payload else None
        return exc.code, parsed


def check(condition, message):
    icon = "[PASS]" if condition else "[FAIL]"
    print(f"  {icon} - {message}")
    return condition


def get_first_id(path, field_name="id"):
    status, payload = req("GET", path)
    if status != 200 or not isinstance(payload, dict):
        return None
    sample = payload.get("sample") or []
    if not sample:
        return None
    return sample[0].get(field_name)


@contextmanager
def local_server():
    app = create_app()
    server = make_server(HOST, PORT, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            try:
                status, _ = req("GET", "/health")
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        yield
    finally:
        server.shutdown()
        thread.join(timeout=5)


def main():
    failures = 0

    with local_server():
        user_id_for_event = get_first_id("/users")
        url_id_for_event = get_first_id("/urls")

        print("\n== TESTING USER SERIALIZATION (Challenge #3) ==\n")

        status, user = req("POST", "/users", {"username": "ch3_test", "email": "ch3@test.com"})
        if status == 409:
            status, user = req("POST", "/users", {"username": "ch3_test_2", "email": "ch3_2@test.com"})
        print(f"POST /users -> {status}")
        print(f"Response: {json.dumps(user, indent=2)}")

        if not check(status == 201, "Status is 201"):
            failures += 1
        if not check("id" in user, "id field present"):
            failures += 1
        if not check("username" in user, "username field present"):
            failures += 1
        if not check("email" in user, "email field present"):
            failures += 1
        if not check("created_at" in user, "created_at field present"):
            failures += 1
        if not check(isinstance(user.get("id"), int), "id is integer"):
            failures += 1
        if not check(isinstance(user.get("created_at"), str), "created_at is string"):
            failures += 1

        uid = user.get("id")

        status, user2 = req("GET", f"/users/{uid}")
        print(f"\nGET /users/{uid} -> {status}")
        print(f"Response: {json.dumps(user2, indent=2)}")
        if not check(status == 200, "Status is 200"):
            failures += 1
        if not check(user2.get("id") == uid, "id matches"):
            failures += 1

        status, user_urls = req("GET", f"/users/{uid}/urls")
        print(f"\nGET /users/{uid}/urls -> {status}")
        if status == 200:
            if not check("kind" in user_urls, "kind field present"):
                failures += 1
            if not check("sample" in user_urls, "sample field present"):
                failures += 1
            if not check("total_items" in user_urls, "total_items field present"):
                failures += 1

        status, user_events = req("GET", f"/users/{uid}/events")
        print(f"GET /users/{uid}/events -> {status}")
        if status == 200:
            if not check("kind" in user_events, "user events kind present"):
                failures += 1
            if not check("sample" in user_events, "user events sample present"):
                failures += 1

        print("\n== TESTING EVENT SERIALIZATION (Challenge #6) ==\n")

        if url_id_for_event is None or user_id_for_event is None:
            print("[FAIL] Could not determine a valid url_id/user_id from localhost seed data")
            return 1

        status, ev1 = req(
            "POST",
            "/events",
            {
                "url_id": url_id_for_event,
                "user_id": user_id_for_event,
                "event_type": "click",
                "details": "referrer:https://google.com",
            },
        )
        print(f"POST /events (with user) -> {status}")
        print(f"Response: {json.dumps(ev1, indent=2)}")

        if not check(status == 201, "Status is 201"):
            failures += 1
        if not check("id" in ev1, "id field present"):
            failures += 1
        if not check("url_id" in ev1, "url_id field present"):
            failures += 1
        if not check("user_id" in ev1, "user_id field present"):
            failures += 1
        if not check("event_type" in ev1, "event_type field present"):
            failures += 1
        if not check("timestamp" in ev1, "timestamp field present"):
            failures += 1
        if not check("details" in ev1, "details field present"):
            failures += 1
        if not check(isinstance(ev1.get("url_id"), int), f"url_id is INTEGER not {type(ev1.get('url_id'))}"):
            failures += 1
        if not check(isinstance(ev1.get("user_id"), int), f"user_id is INTEGER not {type(ev1.get('user_id'))}"):
            failures += 1

        status, ev2 = req(
            "POST",
            "/events",
            {"url_id": url_id_for_event, "event_type": "redirect"},
        )
        print(f"\nPOST /events (no user_id) -> {status}")
        print(f"Response: {json.dumps(ev2, indent=2)}")

        if not check(status == 201, "Status is 201"):
            failures += 1
        if not check(ev2.get("user_id") is None, f"user_id is null not {ev2.get('user_id')}"):
            failures += 1

        eid = ev1.get("id")
        status, ev3 = req("GET", f"/events/{eid}")
        print(f"\nGET /events/{eid} -> {status}")
        if not check(status == 200, "Single event GET works"):
            failures += 1

        status, evlist = req("GET", "/events")
        print(f"\nGET /events -> {status}")
        if isinstance(evlist, dict) and evlist.get("sample"):
            sample_event = evlist["sample"][0]
            print(f"First event in sample: {json.dumps(sample_event, indent=2)}")
            if not check(isinstance(sample_event.get("url_id"), (int, type(None))), "url_id in list is int or null"):
                failures += 1
            if not check(isinstance(sample_event.get("user_id"), (int, type(None))), "user_id in list is int or null"):
                failures += 1

        status, stats = req("GET", "/events/stats")
        print(f"\nGET /events/stats -> {status}")
        if status == 200:
            print(f"Stats: {json.dumps(stats, indent=2)}")
            if not check("total" in stats, "total field present"):
                failures += 1
            if not check("by_type" in stats, "by_type field present"):
                failures += 1

        print("\n======================================")
        if failures == 0:
            print("[PASS] ALL CHECKS PASSED - SAFE TO PUSH")
        else:
            print(f"[FAIL] {failures} CHECKS FAILED - DO NOT PUSH YET")
            print("Fix the failures above then re-run this script")
        print("======================================\n")
        return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
