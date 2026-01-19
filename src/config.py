import os
import sys
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Configuration loader for the Telegram YTDL Bot."""
    
    try:
        API_ID = int(os.getenv("TG_APP_ID", "0"))
        API_HASH = os.getenv("TG_API_HASH", "")
        BOT_TOKEN = os.getenv("TG_BOT_API", "")
    except ValueError:
        print("Error: TG_APP_ID must be an integer.")
        sys.exit(1)

    if not all([API_ID, API_HASH, BOT_TOKEN]):
        print("Error: Required environment variables are missing.")
        print("Please check your .env file and ensure TG_APP_ID, TG_API_HASH, and TG_BOT_API are set.")
        sys.exit(1)
    
    # Whitelist parsing
    _white_list_raw = os.getenv("WHITE_LIST_IDS", "")
    WHITE_LIST = [
        int(i.strip()) for i in _white_list_raw.split(",") 
        if i.strip().isdigit()
    ]
    
    # Database settings
    DB_PATH = "bot_database.db"
    
    # Download settings
    DOWNLOAD_DIR = "downloads"
    COOKIES_FILE = "cookies.txt"
    
    # Ensure mandatory directories exist
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs("log", exist_ok=True)
