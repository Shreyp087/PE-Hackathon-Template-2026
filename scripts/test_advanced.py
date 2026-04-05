import urllib.request
import urllib.error
import json

BASE = "http://localhost:5000"

def req(method, path, body=None, expected_status=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            status = resp.status
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        status = e.code
        body = json.loads(e.read())
    ok = (expected_status is None or status == expected_status)
    icon = "✅" if ok else "❌"
    print(f"{icon} {method} {path} → {status}")
    if not ok:
        print(f"   Expected: {expected_status}, Got: {status}")
        print(f"   Body: {json.dumps(body)[:200]}")
    return status, body

def main():
    print("\n── USERS ──")
    _, u = req("POST", "/users", {"username": "testuser_adv", "email": "adv@test.com"}, 201)
    print(f"   Fields returned: {list(u.keys())}")
    assert "id" in u, "MISSING id"
    assert "username" in u, "MISSING username"
    assert "email" in u, "MISSING email"
    assert "created_at" in u, "MISSING created_at"
    user_id = u["id"]

    req("POST", "/users", {"username": "testuser_adv", "email": "adv@test.com"}, 409)
    req("POST", "/users", {"email": "adv2@test.com"}, 422)
    req("POST", "/users", {"username": "testuser_adv2"}, 422)

    print("\n── URLS ──")
    _, url_obj = req("POST", "/urls", {
        "original_url": "https://example.com",
        "title": "Test",
        "user_id": user_id
    }, 201)
    print(f"   Fields returned: {list(url_obj.keys())}")
    assert "short_code" in url_obj, "MISSING short_code — THIS IS THE ADVANCED CHALLENGE FAILURE"
    assert "id" in url_obj, "MISSING id"
    assert "is_active" in url_obj, "MISSING is_active"
    assert "user_id" in url_obj, "MISSING user_id (as integer)"
    assert isinstance(url_obj.get("user_id"), int), f"user_id is not int: {url_obj.get('user_id')}"
    url_id = url_obj["id"]

    req("POST", "/urls", {"original_url": "https://x.com", "short_code": "custom1"}, 201)
    req("POST", "/urls", {"original_url": "https://x.com", "short_code": "custom1"}, 409)

    print("\n── EVENTS ──")
    _, ev = req("POST", "/events", {
        "url_id": url_id,
        "user_id": user_id,
        "event_type": "click",
        "details": "referrer:https://google.com"
    }, 201)
    print(f"   Fields returned: {list(ev.keys())}")
    assert "id" in ev, "MISSING id"
    assert "url_id" in ev, "MISSING url_id (as integer)"
    assert "user_id" in ev, "MISSING user_id (as integer)"
    assert isinstance(ev.get("url_id"), int), f"url_id is not int: {ev.get('url_id')}"
    assert isinstance(ev.get("user_id"), int), f"user_id is not int: {ev.get('user_id')}"
    assert "event_type" in ev, "MISSING event_type"
    assert "timestamp" in ev, "MISSING timestamp"
    event_id = ev["id"]

    _, ev2 = req("POST", "/events", {
        "url_id": url_id,
        "event_type": "redirect"
    }, 201)
    assert ev2.get("user_id") is None, "user_id should be null when not provided"

    req("POST", "/events", {"url_id": 999999, "event_type": "click"}, 404)
    req("GET", f"/events/{event_id}", None, 200)
    req("DELETE", f"/events/{event_id}", None, 200)

    print("\n── LIST ENVELOPES ──")
    _, ul = req("GET", "/users", None, 200)
    assert ul.get("kind") == "list", f"kind wrong: {ul.get('kind')}"
    assert "sample" in ul, "MISSING sample key"
    assert "total_items" in ul, "MISSING total_items key"
    assert isinstance(ul["total_items"], int), "total_items must be int"

    _, urll = req("GET", "/urls", None, 200)
    assert urll.get("kind") == "list"
    assert "sample" in urll
    assert "total_items" in urll

    _, el = req("GET", "/events", None, 200)
    assert el.get("kind") == "list"
    assert "sample" in el
    assert "total_items" in el

    print("\n══ ALL ASSERTIONS PASSED — SAFE TO PUSH ══\n")


if __name__ == "__main__":
    main()
