from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    TextField,
)

from app.database import BaseModel


class User(BaseModel):
    id = AutoField(primary_key=True)
    username = CharField(unique=True, max_length=64)
    email = CharField(unique=True, max_length=255)
    created_at = DateTimeField(default=datetime.utcnow)


class URL(BaseModel):
    id = AutoField(primary_key=True)
    user = ForeignKeyField(
        User,
        backref="urls",
        null=True,
        on_delete="SET NULL",
        column_name="user_id",
    )
    short_code = CharField(unique=True, max_length=16, index=True)
    original_url = TextField(column_name="original_url")
    title = CharField(null=True, max_length=255)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    is_active = BooleanField(default=True)
    click_count = IntegerField(default=0)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class Event(BaseModel):
    id = AutoField(primary_key=True)
    url = ForeignKeyField(
        URL,
        backref="events",
        null=True,
        on_delete="SET NULL",
        column_name="url_id",
    )
    user = ForeignKeyField(
        User,
        backref="events",
        null=True,
        on_delete="SET NULL",
        column_name="user_id",
    )
    event_type = CharField(max_length=32)
    timestamp = DateTimeField(default=datetime.utcnow)
    details = TextField(null=True)


__all__ = ["User", "URL", "Event"]
