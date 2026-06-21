import asyncio
import hashlib
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

import feedparser
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.ai_filter import filter_articles
from app.models import Article, Feed, Interest, SeenGuid

logger = logging.getLogger(__name__)

# feedparser はデフォルトでネットワークタイムアウトを持たないため、応答しない
# フィードがあるとフェッチが無限にハングし、ワーカースレッドを占有してしまう。
# socket のデフォルトタイムアウトを設定して取りこぼしを防ぐ（httpx は独自に
# タイムアウトを管理するため影響しない）。
socket.setdefaulttimeout(float(os.getenv("FEED_FETCH_TIMEOUT", "20")))


def _entry_guid(entry) -> str:
    guid = entry.get("id") or entry.get("link", "")
    if guid:
        return guid
    # Stable synthetic key for feeds that omit both id and link.
    key = f"{entry.get('title', '')}\x00{entry.get('published', '')}"
    return "synthetic:" + hashlib.sha1(key.encode()).hexdigest()


def setup_scheduler() -> AsyncIOScheduler:
    db_path = os.getenv("DB_PATH", "data/news.db")
    jobstore = SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    scheduler = AsyncIOScheduler(jobstores={"default": jobstore})

    # 全フィードを同時に起動すると LLM へのリクエストが殺到して
    # タイムアウトするため、初回実行を数秒ずつずらす（thundering herd 回避）。
    base = datetime.now(timezone.utc)
    stagger = int(os.getenv("FEED_START_STAGGER_SEC", "10"))
    for i, feed in enumerate(Feed.select().where(Feed.enabled == True)):  # noqa: E712
        scheduler.add_job(
            _poll_feed,
            trigger=IntervalTrigger(minutes=feed.interval_min),
            id=f"feed_{feed.id}",
            args=[feed.id],
            replace_existing=True,
            next_run_time=base + timedelta(seconds=i * stagger),
        )

    return scheduler


async def _poll_feed(feed_id: int) -> None:
    try:
        feed = Feed.get_by_id(feed_id)
    except Feed.DoesNotExist:
        return
    if not feed.enabled:
        return

    loop = asyncio.get_running_loop()
    try:
        parsed = await loop.run_in_executor(
            None,
            lambda: feedparser.parse(feed.url, etag=feed.etag, modified=feed.last_modified),
        )
    except Exception as exc:
        # フェッチ失敗（タイムアウト等）。今回はスキップし次回ポーリングでリトライ。
        logger.warning("feed %d fetch failed: %s: %s", feed_id, type(exc).__name__, exc)
        return

    now = datetime.utcnow()

    if getattr(parsed, "status", None) == 304:
        Feed.update(last_fetched_at=now).where(Feed.id == feed_id).execute()
        return

    incoming: dict[str, object] = {
        _entry_guid(entry): entry for entry in parsed.get("entries", [])
    }

    if not incoming:
        Feed.update(last_fetched_at=now).where(Feed.id == feed_id).execute()
        return

    # Query only the incoming GUIDs — avoids loading full history into memory.
    seen = {
        row.guid
        for row in SeenGuid.select(SeenGuid.guid).where(
            SeenGuid.feed == feed_id,
            SeenGuid.guid.in_(list(incoming.keys())),
        )
    }

    new_entries = [entry for guid, entry in incoming.items() if guid not in seen]

    if not new_entries:
        Feed.update(last_fetched_at=now).where(Feed.id == feed_id).execute()
        return

    interest_descriptions = [i.description for i in Interest.select(Interest.description)]

    entry_dicts = []
    for entry in new_entries:
        guid = _entry_guid(entry)
        published_at = None
        if entry.get("published_parsed"):
            try:
                published_at = datetime(*entry.published_parsed[:6])
            except (TypeError, ValueError):
                pass
        entry_dicts.append(
            {
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "guid": guid,
                "url": entry.get("link", ""),
                "published_at": published_at,
            }
        )

    if interest_descriptions:
        matched, errored = await filter_articles(entry_dicts, interest_descriptions)
    else:
        matched, errored = [], []

    matched_guids = set()
    for entry_dict, reason in matched:
        try:
            inserted = (
                Article.insert(
                    feed=feed_id,
                    guid=entry_dict["guid"],
                    title=entry_dict["title"],
                    summary=entry_dict["summary"] or None,
                    url=entry_dict["url"],
                    published_at=entry_dict["published_at"],
                    ai_reason=reason,
                )
                .on_conflict_ignore()
                .execute()
            )
            if inserted:
                matched_guids.add(entry_dict["guid"])
        except Exception:
            logger.exception("Failed to insert article guid=%r", entry_dict["guid"])

    # LLM 呼び出しが失敗した記事は seen 扱いにせず、次回ポーリングでリトライする。
    errored_guids = {entry["guid"] for entry in errored}
    seen_rows = [
        {"feed": feed_id, "guid": guid}
        for guid in incoming
        if guid not in errored_guids
    ]
    if seen_rows:
        SeenGuid.insert_many(seen_rows).on_conflict_ignore().execute()

    Feed.update(
        last_fetched_at=now,
        etag=getattr(parsed, "etag", None) or feed.etag,
        last_modified=getattr(parsed, "modified", None) or feed.last_modified,
    ).where(Feed.id == feed_id).execute()

    logger.info(
        "feed %d polled: %d new entries, %d matched",
        feed_id,
        len(new_entries),
        len(matched_guids),
    )


async def add_feed_job(scheduler: AsyncIOScheduler, feed: Feed) -> None:
    scheduler.add_job(
        _poll_feed,
        trigger=IntervalTrigger(minutes=feed.interval_min),
        id=f"feed_{feed.id}",
        args=[feed.id],
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )


async def remove_feed_job(scheduler: AsyncIOScheduler, feed_id: int) -> None:
    job_id = f"feed_{feed_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
