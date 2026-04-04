import argparse
import csv
import logging
from datetime import datetime
from pathlib import Path

from dateutil.parser import parse as parse_datetime
from dotenv import load_dotenv
from peewee import PeeweeException

from app.database import initialize_db
from app.logger import setup_logging
from app.models import Event, URL, User

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)


def _row_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _parse_datetime(value):
    try:
        if value and value.strip():
            return parse_datetime(value.strip())
    except (TypeError, ValueError, OverflowError) as exc:
        logger.warning(
            "invalid_datetime",
            extra={"value": value, "error": str(exc)},
        )
    return datetime.utcnow()


def _parse_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_users(filepath, db):
    created = 0
    skipped = 0

    with filepath.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        with db.atomic():
            for row_number, row in enumerate(reader, start=2):
                try:
                    _, was_created = User.get_or_create(
                        email=row["email"].strip(),
                        defaults={"username": row["username"].strip()},
                    )
                    if was_created:
                        created += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    skipped += 1
                    logger.warning(
                        "seed_user_row_failed",
                        extra={
                            "row_number": row_number,
                            "email": row.get("email"),
                            "error": str(exc),
                        },
                    )

    logger.info(
        "users_loaded",
        extra={
            "filepath": str(filepath),
            "created_count": created,
            "skipped_count": skipped,
        },
    )


def load_urls(filepath, db):
    created = 0
    skipped = 0

    with filepath.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        with db.atomic():
            for row_number, row in enumerate(reader, start=2):
                try:
                    user_id = int(row["user_id"])
                    user = User.get_by_id(user_id)
                except (TypeError, ValueError, User.DoesNotExist) as exc:
                    skipped += 1
                    logger.warning(
                        "seed_url_user_missing",
                        extra={
                            "row_number": row_number,
                            "user_id": row.get("user_id"),
                            "error": str(exc),
                        },
                    )
                    continue

                try:
                    _, was_created = URL.get_or_create(
                        short_code=row["short_code"].strip(),
                        defaults={
                            "original_url": _row_value(
                                row, "original_url", "Original_url"
                            ).strip(),
                            "title": (row.get("title") or "").strip() or None,
                            "user": user,
                            "created_at": _parse_datetime(
                                _row_value(row, "created_at", "Created_at")
                            ),
                            "updated_at": _parse_datetime(
                                _row_value(row, "updated_at", "Updated_at")
                            ),
                            "is_active": _parse_bool(row.get("is_active")),
                        },
                    )
                    if was_created:
                        created += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    skipped += 1
                    logger.warning(
                        "seed_url_row_failed",
                        extra={
                            "row_number": row_number,
                            "short_code": row.get("short_code"),
                            "error": str(exc),
                        },
                    )

    logger.info(
        "urls_loaded",
        extra={
            "filepath": str(filepath),
            "created_count": created,
            "skipped_count": skipped,
        },
    )


def load_events(filepath, db):
    created = 0
    skipped = 0

    with filepath.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        with db.atomic():
            for row_number, row in enumerate(reader, start=2):
                try:
                    url = URL.get_by_id(int(row["url_id"]))
                except (TypeError, ValueError, URL.DoesNotExist) as exc:
                    skipped += 1
                    logger.warning(
                        "seed_event_url_missing",
                        extra={
                            "row_number": row_number,
                            "url_id": row.get("url_id"),
                            "error": str(exc),
                        },
                    )
                    continue

                user = None
                user_value = row.get("user_id")
                if user_value and user_value.strip():
                    try:
                        user = User.get_by_id(int(user_value))
                    except (TypeError, ValueError, User.DoesNotExist) as exc:
                        logger.warning(
                            "seed_event_user_missing",
                            extra={
                                "row_number": row_number,
                                "user_id": user_value,
                                "error": str(exc),
                            },
                        )

                try:
                    Event.create(
                        url=url,
                        user=user,
                        event_type=row["event_type"].strip(),
                        timestamp=_parse_datetime(row.get("timestamp")),
                        details=(row.get("details") or "").strip() or None,
                    )
                    created += 1
                except Exception as exc:
                    skipped += 1
                    logger.warning(
                        "seed_event_row_failed",
                        extra={
                            "row_number": row_number,
                            "url_id": row.get("url_id"),
                            "error": str(exc),
                        },
                    )

    logger.info(
        "events_loaded",
        extra={
            "filepath": str(filepath),
            "created_count": created,
            "skipped_count": skipped,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=Path)
    parser.add_argument("--urls", type=Path)
    parser.add_argument("--events", type=Path)
    args = parser.parse_args()

    db = initialize_db()

    try:
        db.connect(reuse_if_open=True)

        if args.users:
            load_users(args.users, db)
        if args.urls:
            load_urls(args.urls, db)
        if args.events:
            load_events(args.events, db)
    except PeeweeException as exc:
        logger.error("seed_failed", extra={"error": str(exc)}, exc_info=True)
        raise
    finally:
        if not db.is_closed():
            db.close()


if __name__ == "__main__":
    main()
