import os
from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CompositeKey,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

db = SqliteDatabase(
    os.getenv("DB_PATH", "data/news.db"),
    pragmas={"foreign_keys": 1},
)


class BaseModel(Model):
    class Meta:
        database = db


class Feed(BaseModel):
    id = AutoField()
    url = TextField(unique=True)
    name = TextField()
    interval_min = IntegerField(default=60)
    enabled = BooleanField(default=True)
    last_fetched_at = DateTimeField(null=True)
    etag = TextField(null=True)
    last_modified = TextField(null=True)


class Interest(BaseModel):
    id = AutoField()
    name = TextField()
    description = TextField()


class Article(BaseModel):
    id = AutoField()
    feed = ForeignKeyField(Feed, backref="articles", on_delete="CASCADE")
    guid = TextField()
    title = TextField()
    summary = TextField(null=True)
    url = TextField()
    published_at = DateTimeField(null=True)
    ai_reason = TextField(null=True)
    saved_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = ((("feed", "guid"), True),)  # UNIQUE(feed_id, guid)


class SeenGuid(BaseModel):
    feed = ForeignKeyField(Feed, on_delete="CASCADE")
    guid = TextField()

    class Meta:
        primary_key = CompositeKey("feed", "guid")


def init_db() -> None:
    db.connect(reuse_if_open=True)
    db.create_tables([Feed, Interest, Article, SeenGuid], safe=True)
