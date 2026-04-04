import argparse
import random
import string
from datetime import datetime, timedelta

from dotenv import load_dotenv
from faker import Faker
from peewee import fn

from app.database import initialize_db

load_dotenv()
db = initialize_db()

from app.models import Event, URL, User


BATCH_SIZE_USERS = 100
BATCH_SIZE_URLS = 100
BATCH_SIZE_EVENTS = 500
SHORT_CODE_ALPHABET = string.ascii_letters + string.digits
REALISTIC_DOMAINS = [
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
EVENT_TYPES = [
    ("redirect", 0.70),
    ("create", 0.15),
    ("preview", 0.10),
    ("error", 0.05),
]

fake = Faker()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate realistic bulk data for Grafana dashboards."
    )
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--urls", type=int, default=200)
    parser.add_argument("--events", type=int, default=2000)
    parser.add_argument("--days", type=int, default=30)
    return parser.parse_args()


def chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def extract_ids(rows):
    extracted = []
    for row in rows:
        if hasattr(row, "id"):
            extracted.append(row.id)
        elif isinstance(row, (tuple, list)) and row:
            extracted.append(row[0])
        else:
            extracted.append(row)
    return extracted


def random_past_datetime(days):
    now = datetime.utcnow()
    total_seconds = max(days, 1) * 24 * 60 * 60
    offset_seconds = random.uniform(0, total_seconds)
    return now - timedelta(seconds=offset_seconds)


def recent_weighted_datetime(days):
    now = datetime.utcnow()
    raw_days = random.expovariate(0.1)
    offset_days = min(raw_days, max(days, 1))
    offset_seconds = random.uniform(0, 24 * 60 * 60)
    candidate = now - timedelta(days=offset_days, seconds=offset_seconds)
    minimum = now - timedelta(days=max(days, 1))
    if candidate < minimum:
        return minimum
    return candidate


def build_unique_short_codes(count):
    existing_codes = set(URL.select(URL.short_code).tuples())
    normalized_codes = {code[0] if isinstance(code, tuple) else code for code in existing_codes}
    short_codes = []
    while len(short_codes) < count:
        candidate = "".join(random.choice(SHORT_CODE_ALPHABET) for _ in range(6))
        if candidate in normalized_codes:
            continue
        normalized_codes.add(candidate)
        short_codes.append(candidate)
    return short_codes


def load_fake_users(n):
    if n <= 0:
        return []

    created_ids = []
    records = []

    for _ in range(n):
        created_at = random_past_datetime(30)
        records.append(
            {
                "username": fake.unique.user_name()[:64],
                "email": fake.unique.safe_email()[:255],
                "created_at": created_at,
            }
        )

    with db.atomic():
        for batch in chunked(records, BATCH_SIZE_USERS):
            rows = (
                User.insert_many(batch)
                .returning(User.id)
                .execute()
            )
            created_ids.extend(extract_ids(rows))

    return created_ids


def load_fake_urls(n, user_ids, days):
    if n <= 0:
        return []

    created_ids = []
    records = []
    short_codes = build_unique_short_codes(n)
    now = datetime.utcnow()

    for short_code in short_codes:
        created_at = random_past_datetime(days)
        updated_at = created_at + timedelta(hours=random.randint(0, 48))
        if updated_at > now:
            updated_at = now

        if random.random() < 0.5:
            original_url = fake.uri()
        else:
            original_url = random.choice(REALISTIC_DOMAINS)

        user_id = random.choice(user_ids) if user_ids and random.random() < 0.8 else None

        records.append(
            {
                "short_code": short_code,
                "original_url": original_url,
                "user": user_id,
                "title": fake.catch_phrase()[:255],
                "is_active": random.random() < 0.9,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

    with db.atomic():
        for batch in chunked(records, BATCH_SIZE_URLS):
            rows = (
                URL.insert_many(batch)
                .returning(URL.id)
                .execute()
            )
            created_ids.extend(extract_ids(rows))

    return created_ids


def pick_event_type():
    roll = random.random()
    cumulative = 0.0
    for event_type, weight in EVENT_TYPES:
        cumulative += weight
        if roll <= cumulative:
            return event_type
    return EVENT_TYPES[-1][0]


def load_fake_events(n, url_ids, user_ids, days):
    if n <= 0 or not url_ids:
        return

    records = []
    with db.atomic():
        for _ in range(n):
            event_type = pick_event_type()
            details = fake.sentence() if event_type == "error" else None
            records.append(
                {
                    "url": random.choice(url_ids),
                    "user": random.choice(user_ids) if user_ids and random.random() < 0.6 else None,
                    "event_type": event_type,
                    "timestamp": recent_weighted_datetime(days),
                    "details": details,
                }
            )

        for batch in chunked(records, BATCH_SIZE_EVENTS):
            Event.insert_many(batch).execute()


def update_click_counts(url_ids):
    if not url_ids:
        return

    with db.atomic():
        URL.update(click_count=0).where(URL.id.in_(url_ids)).execute()

        redirect_counts = (
            Event.select(Event.url, fn.COUNT(Event.id).alias("redirect_count"))
            .where((Event.url.in_(url_ids)) & (Event.event_type == "redirect"))
            .group_by(Event.url)
            .tuples()
        )

        for url_id, redirect_count in redirect_counts:
            URL.update(click_count=redirect_count).where(URL.id == url_id).execute()


def main():
    args = parse_args()
    user_count = max(0, args.users)
    url_count = max(0, args.urls)
    event_count = max(0, args.events)
    days = max(1, args.days)

    user_ids = load_fake_users(user_count)
    url_ids = load_fake_urls(url_count, user_ids, days)
    load_fake_events(event_count, url_ids, user_ids, days)
    update_click_counts(url_ids)

    print(f"users: {User.select().count()}")
    print(f"urls: {URL.select().count()}")
    print(f"events: {Event.select().count()}")


if __name__ == "__main__":
    main()
