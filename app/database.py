import os
from urllib.parse import urlparse

from peewee import DatabaseProxy, Model, PostgresqlDatabase

db_proxy = DatabaseProxy()


class BaseModel(Model):
    class Meta:
        database = db_proxy


def initialize_db(app=None):
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        parsed = urlparse(database_url)
        db_name = parsed.path.lstrip("/") or os.getenv("DB_NAME", "hackathon_db")
        db_user = parsed.username or os.getenv("DB_USER", "postgres")
        db_password = parsed.password or os.getenv("DB_PASSWORD", "postgres")
        db_host = parsed.hostname or os.getenv("DB_HOST", "localhost")
        db_port = parsed.port or int(os.getenv("DB_PORT", "5432"))
    else:
        db_name = os.getenv("DB_NAME", "hackathon_db")
        db_user = os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DB_PASSWORD", "postgres")
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = int(os.getenv("DB_PORT", "5432"))

    db = PostgresqlDatabase(
        db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port,
        connect_timeout=2,
    )
    db_proxy.initialize(db)

    from app.models import Event, URL, User

    try:
        with db:
            db.create_tables([User, URL, Event], safe=True)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Database initialization failed or is offline: {e}")

    return db


init_db = initialize_db


__all__ = ["db_proxy", "BaseModel", "initialize_db", "init_db"]
