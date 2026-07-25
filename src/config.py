import os
from dotenv import load_dotenv

load_dotenv()


def _parse_whitelist(raw):
    """Parse a comma-separated list of Telegram user IDs (ignores non-numeric)."""
    return [int(i.strip()) for i in (raw or "").split(",") if i.strip().isdigit()]


def _parse_int(raw, default=0):
    """Best-effort int from an env value; a malformed value must not break import."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


class Config:
    """Configuration loaded from environment variables.

    This is the single source of truth: no other module reads os.environ, so a
    test can monkeypatch an attribute here and every consumer sees it.

    Reading env values here is side-effect free (no exit, no mkdir) so the package
    can be imported in tests without credentials. Call ``Config.validate()`` and
    ``Config.ensure_dirs()`` explicitly from ``main()`` at startup.
    """

    # Telegram credentials (env var names differ from these attribute names)
    API_ID = _parse_int(os.getenv("TG_APP_ID"), 0)
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

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Downloading + transcoding are CPU/disk bound; cap how many run at once
    MAX_CONCURRENT_DOWNLOADS = _parse_int(os.getenv("MAX_CONCURRENT_DOWNLOADS"), 2)

    # PO Token provider (bgutil HTTP server) for unlocking high-quality YouTube formats
    POT_PROVIDER_URL = os.getenv("POT_PROVIDER_URL", "http://127.0.0.1:4416")

    # Instagram: proxy is what enables the direct (best quality) endpoints; without
    # one the client falls back to the fixer service.
    IG_PROXY_URL = os.getenv("IG_PROXY_URL", "").strip()

    # doc_ids and fixer hosts change over time; override via env without a code change.
    IG_FIXER_URL = os.getenv("IG_FIXER_URL", "https://www.instagram7.com").rstrip("/")
    # Fallback offload base; the real one is derived per-request from the fixer's
    # og:video (services move the offload host around). Defaults to the fixer host.
    IG_OFFLOAD_BASE = os.getenv("IG_OFFLOAD_BASE", f"{IG_FIXER_URL}/offload").rstrip("/")
    IG_MOBILE_DOC_ID = os.getenv("IG_MOBILE_DOC_ID", "8845758582119845")
    IG_WEB_DOC_ID = os.getenv("IG_WEB_DOC_ID", "25531498899829322")

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
