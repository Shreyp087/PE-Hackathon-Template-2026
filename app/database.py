import os

from peewee import DatabaseProxy, Model, PostgresqlDatabase

db_proxy = DatabaseProxy()


class BaseModel(Model):
    class Meta:
        database = db_proxy


def initialize_db(app=None):
    db = PostgresqlDatabase(
        os.getenv("DB_NAME", "hackathon_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
    )
    db_proxy.initialize(db)

    from app.models import Event, URL, User

    with db:
        db.create_tables([User, URL, Event], safe=True)

    return db


init_db = initialize_db


__all__ = ["db_proxy", "BaseModel", "initialize_db", "init_db"]
