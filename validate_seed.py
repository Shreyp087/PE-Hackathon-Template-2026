import json
import logging

from dotenv import load_dotenv
from peewee import fn

from app.database import initialize_db
from app.models import Event, URL, User

logger = logging.getLogger(__name__)


def main():
    load_dotenv()
    db = initialize_db()

    try:
        db.connect(reuse_if_open=True)

        report = {
            "users": User.select().count(),
            "urls": URL.select().count(),
            "urls_active": URL.select().where(URL.is_active == True).count(),
            "events": Event.select().count(),
            "event_types": {
                event_type: count
                for event_type, count in (
                    Event.select(Event.event_type, fn.COUNT(Event.id).alias("count"))
                    .group_by(Event.event_type)
                    .tuples()
                )
            },
        }

        if report["users"] == 0:
            logger.warning("users table has 0 rows")
        if report["urls"] == 0:
            logger.warning("urls table has 0 rows")
        if report["urls_active"] == 0:
            logger.warning("no active urls found")
        if report["events"] == 0:
            logger.warning("events table has 0 rows")

        print(json.dumps(report, indent=2))
    finally:
        if not db.is_closed():
            db.close()


if __name__ == "__main__":
    main()
