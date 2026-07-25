"""Cache-layer tests. Every test uses a tmp_path db file, never Config.DB_PATH."""

import aiosqlite
import pytest

from src.storage.database import Database


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "cache.db")


async def table_names(db_path):
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cur:
            return {row[0] for row in await cur.fetchall()}


async def test_initialize_is_idempotent(db_path):
    db = Database(db_path)
    await db.initialize()
    await db.initialize()

    await db.add_file_id("youtube", "abc", "file-1", "Title")
    assert await db.get_file_id("youtube", "abc") == "file-1"


async def test_add_and_get_round_trip(db_path):
    db = Database(db_path)
    await db.initialize()

    await db.add_file_id("youtube", "dQw4w9WgXcQ", "BAADfile", "Never Gonna Give You Up")

    assert await db.get_file_id("youtube", "dQw4w9WgXcQ") == "BAADfile"


async def test_same_video_id_on_two_platforms_stays_separate(db_path):
    """The bug that motivated the composite key: generic extractors reuse short ids."""
    db = Database(db_path)
    await db.initialize()

    await db.add_file_id("vk", "456239018", "vk-file", "VK clip")
    await db.add_file_id("vimeo", "456239018", "vimeo-file", "Vimeo clip")

    assert await db.get_file_id("vk", "456239018") == "vk-file"
    assert await db.get_file_id("vimeo", "456239018") == "vimeo-file"

    async with aiosqlite.connect(db_path) as raw:
        async with raw.execute("SELECT COUNT(*) FROM videos") as cur:
            assert (await cur.fetchone())[0] == 2


async def test_miss_returns_none(db_path):
    db = Database(db_path)
    await db.initialize()

    await db.add_file_id("youtube", "abc", "file-1", "Title")

    assert await db.get_file_id("youtube", "nope") is None
    assert await db.get_file_id("pornhub", "abc") is None


async def test_upsert_refreshes_stale_file_id(db_path):
    db = Database(db_path)
    await db.initialize()

    await db.add_file_id("youtube", "abc", "dead-file", "Old title")
    await db.add_file_id("youtube", "abc", "fresh-file", "New title")

    assert await db.get_file_id("youtube", "abc") == "fresh-file"

    async with aiosqlite.connect(db_path) as raw:
        async with raw.execute("SELECT COUNT(*), title FROM videos") as cur:
            count, title = await cur.fetchone()
    assert count == 1
    assert title == "New title"


async def test_none_platform_and_title_are_normalized(db_path):
    db = Database(db_path)
    await db.initialize()

    await db.add_file_id(None, "xyz", "file-none", None)

    assert await db.get_file_id(None, "xyz") == "file-none"
    # None and "" have to resolve to the same row, otherwise a probe that yields
    # no platform would never hit its own cache entry.
    assert await db.get_file_id("", "xyz") == "file-none"

    async with aiosqlite.connect(db_path) as raw:
        async with raw.execute("SELECT platform, title FROM videos") as cur:
            assert await cur.fetchone() == ("", "")


async def create_legacy_db(db_path):
    """The pre-migration shape: UNIQUE on video_id alone, nullable columns, no created_at."""
    async with aiosqlite.connect(db_path) as raw:
        await raw.execute("""
            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE,
                platform TEXT,
                telegram_file_id TEXT,
                title TEXT
            )
        """)
        await raw.executemany(
            "INSERT INTO videos (video_id, platform, telegram_file_id, title) VALUES (?, ?, ?, ?)",
            [
                ("dQw4w9WgXcQ", "youtube", "yt-file", "Rick"),
                ("456239018", None, "unknown-file", "Mystery"),
                ("broken", "youtube", None, "No file id"),
            ],
        )
        await raw.commit()


async def test_migration_preserves_rows_and_drops_legacy_table(db_path):
    await create_legacy_db(db_path)

    db = Database(db_path)
    await db.initialize()

    assert await db.get_file_id("youtube", "dQw4w9WgXcQ") == "yt-file"
    # NULL platform lands under the empty-string platform.
    assert await db.get_file_id(None, "456239018") == "unknown-file"
    # A row without a file_id is not a usable cache entry, so it is dropped.
    assert await db.get_file_id("youtube", "broken") is None

    assert "videos_legacy" not in await table_names(db_path)

    async with aiosqlite.connect(db_path) as raw:
        async with raw.execute("SELECT COUNT(*) FROM videos") as cur:
            assert (await cur.fetchone())[0] == 2


async def test_migration_installs_composite_unique_and_is_idempotent(db_path):
    await create_legacy_db(db_path)

    db = Database(db_path)
    await db.initialize()
    await db.initialize()

    # The composite key is live: the legacy id is now reusable under another platform.
    await db.add_file_id("vimeo", "456239018", "vimeo-file", "Vimeo clip")
    assert await db.get_file_id(None, "456239018") == "unknown-file"
    assert await db.get_file_id("vimeo", "456239018") == "vimeo-file"

    # ...and video_id alone is no longer unique-constrained.
    async with aiosqlite.connect(db_path) as raw:
        async with raw.execute("PRAGMA index_list('videos')") as cur:
            indexes = await cur.fetchall()
        unique_column_sets = []
        for index in indexes:
            if not index[2]:
                continue
            async with raw.execute(f"PRAGMA index_info('{index[1]}')") as cur:
                unique_column_sets.append({row[2] for row in await cur.fetchall()})
    assert {"platform", "video_id"} in unique_column_sets
    assert {"video_id"} not in unique_column_sets

    # created_at is populated by the schema default, including for migrated rows.
    async with aiosqlite.connect(db_path) as raw:
        async with raw.execute("SELECT COUNT(*) FROM videos WHERE created_at IS NULL") as cur:
            assert (await cur.fetchone())[0] == 0

    assert "videos_legacy" not in await table_names(db_path)
