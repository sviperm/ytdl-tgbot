import os
from dotenv import load_dotenv

load_dotenv()


def _parse_whitelist(raw):
    """Parse a comma-separated list of Telegram user IDs (ignores non-numeric)."""
    return [int(i.strip()) for i in (raw or "").split(",") if i.strip().isdigit()]


class Config:
    """Configuration loaded from environment variables.

    Reading env values here is side-effect free (no exit, no mkdir) so the package
    can be imported in tests without credentials. Call ``Config.validate()`` and
    ``Config.ensure_dirs()`` explicitly from ``main()`` at startup.
    """

    # Telegram credentials (env var names differ from these attribute names)
    try:
        API_ID = int(os.getenv("TG_APP_ID") or 0)
    except ValueError:
        API_ID = 0
    API_HASH = os.getenv("TG_API_HASH", "")
    BOT_TOKEN = os.getenv("TG_BOT_API", "")

    # Optional whitelist; empty means everyone is allowed
    WHITE_LIST = _parse_whitelist(os.getenv("WHITE_LIST_IDS", ""))

    # Directories (env-overridable so tests can redirect them at a tmp path)
    DATA_DIR = os.getenv("DATA_DIR", "data")
    DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
    LOG_DIR = os.getenv("LOG_DIR", "log")

    DB_PATH = os.path.join(DATA_DIR, "bot_database.db")
    COOKIES_FILE = os.path.join(DATA_DIR, "cookies.txt")

    # PO Token provider (bgutil HTTP server) for unlocking high-quality YouTube formats
    POT_PROVIDER_URL = os.getenv("POT_PROVIDER_URL", "http://127.0.0.1:4416")

    @classmethod
    def validate(cls):
        """Exit early with a clear message if required credentials are missing."""
        if not all([cls.API_ID, cls.API_HASH, cls.BOT_TOKEN]):
            raise SystemExit(
                "Error: required environment variables are missing. "
                "Set TG_APP_ID (non-zero int), TG_API_HASH and TG_BOT_API in your .env file."
            )

    @classmethod
    def ensure_dirs(cls):
        """Create the runtime directories the bot writes to."""
        for directory in (cls.DATA_DIR, cls.DOWNLOAD_DIR, cls.LOG_DIR):
            os.makedirs(directory, exist_ok=True)
