import aiosqlite
from src.config import Config

class Database:
    """Handles all SQLite database operations for video caching."""
    def __init__(self, db_path=Config.DB_PATH):
        self.db_path = db_path

    async def initialize(self):
        """Creates the videos table if it doesn't already exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE,
                    platform TEXT,
                    telegram_file_id TEXT,
                    title TEXT
                )
            """)
            await db.commit()

    async def get_video(self, video_id):
        """Retrieves a cached telegram_file_id by its source video_id."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT telegram_file_id FROM videos WHERE video_id = ?", (video_id,)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else None

    async def add_video(self, video_id, platform, telegram_file_id, title):
        """Stores a new video mapping in the database."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO videos (video_id, platform, telegram_file_id, title) VALUES (?, ?, ?, ?)",
                (video_id, platform, telegram_file_id, title)
            )
            await db.commit()
