import aiosqlite

from src.config import Config

_CREATE_VIDEOS = """
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL DEFAULT '',
        video_id TEXT NOT NULL,
        telegram_file_id TEXT NOT NULL,
        title TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(platform, video_id)
    )
"""

# Scratch name used only inside the migration transaction.
_LEGACY_TABLE = "videos_legacy"


class Database:
    """Cache mapping a (platform, source video_id) pair to a Telegram file_id.

    The platform is part of the key because yt-dlp's generic/VK/Vimeo extractors
    hand out short, non-namespaced ids ("123", "456239018") that collide across
    sites — keyed on video_id alone the bot would resend a foreign video.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or Config.DB_PATH

    async def initialize(self):
        # isolation_level=None: sqlite3 does not open an implicit transaction for
        # DDL, so the migration below has to drive BEGIN/COMMIT itself.
        async with aiosqlite.connect(self.db_path, isolation_level=None) as db:
            if await self._needs_migration(db):
                await self._migrate(db)
            else:
                await db.execute(_CREATE_VIDEOS)

    async def get_file_id(self, platform, video_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT telegram_file_id FROM videos WHERE platform = ? AND video_id = ?",
                (platform or "", video_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def add_file_id(self, platform, video_id, file_id, title):
        async with aiosqlite.connect(self.db_path) as db:
            # Upsert rather than INSERT OR IGNORE: when Telegram invalidates a
            # file_id the orchestrator re-downloads, and that fresh id has to
            # replace the dead one or the row stays broken forever.
            await db.execute(
                "INSERT INTO videos (platform, video_id, telegram_file_id, title) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(platform, video_id) DO UPDATE SET "
                "telegram_file_id = excluded.telegram_file_id, title = excluded.title",
                (platform or "", video_id, file_id, title or ""),
            )
            await db.commit()

    async def _needs_migration(self, db):
        """True when a `videos` table exists but predates UNIQUE(platform, video_id).

        The old shape carried the UNIQUE on video_id alone, so it is recognised by
        the absence of a unique index spanning both key columns.
        """
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'videos'"
        ) as cursor:
            if not await cursor.fetchone():
                return False

        async with db.execute("PRAGMA index_list('videos')") as cursor:
            indexes = await cursor.fetchall()

        for index in indexes:
            name, unique = index[1], index[2]
            if not unique:
                continue
            async with db.execute(f"PRAGMA index_info('{name}')") as cursor:
                columns = {row[2] for row in await cursor.fetchall()}
            if columns == {"platform", "video_id"}:
                return False
        return True

    async def _migrate(self, db):
        """Rebuild `videos` under the composite key, preserving existing rows.

        All in one transaction so a crash mid-way rolls back to the old table
        instead of leaving both shapes behind for the next initialize() to trip on.
        """
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(f"ALTER TABLE videos RENAME TO {_LEGACY_TABLE}")
            await db.execute(_CREATE_VIDEOS)
            # Legacy columns were nullable; NOT NULL now, hence the COALESCE. Rows
            # missing a video_id or file_id are useless as cache entries — dropping
            # them just means the next request re-downloads.
            await db.execute(f"""
                INSERT INTO videos (platform, video_id, telegram_file_id, title)
                SELECT COALESCE(platform, ''), video_id, COALESCE(telegram_file_id, ''), title
                FROM {_LEGACY_TABLE}
                WHERE video_id IS NOT NULL AND telegram_file_id IS NOT NULL
            """)
            await db.execute(f"DROP TABLE {_LEGACY_TABLE}")
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise
