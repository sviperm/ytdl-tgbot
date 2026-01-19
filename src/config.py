import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_ID: int = int(os.getenv("TG_APP_ID"))  # type: ignore
    API_HASH: str = os.getenv("TG_API_HASH")  # type: ignore
    BOT_TOKEN = os.getenv("TG_BOT_API")

    # Whitelist
    white_list_raw = os.getenv("WHITE_LIST_IDS", "")
    WHITE_LIST = [int(i.strip()) for i in white_list_raw.split(",") if i.strip().isdigit()]

    # Database settings
    DB_PATH = "bot_database.db"

    # Download settings
    DOWNLOAD_DIR = "downloads"
    COOKIES_FILE = "cookies.txt"

    # Ensure download directory exists
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
