import logging
import os
from datetime import datetime

class DailyFileHandler(logging.FileHandler):
    def __init__(self, log_dir, encoding="utf-8"):
        self.log_dir = log_dir
        self.encoding = encoding
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(self.log_dir, f"{self.current_date}.log")
        super().__init__(log_file, encoding=self.encoding)

    def emit(self, record):
        new_date = datetime.now().strftime("%Y-%m-%d")
        if new_date != self.current_date:
            self.current_date = new_date
            self.baseFilename = os.path.abspath(os.path.join(self.log_dir, f"{self.current_date}.log"))
            self.close()
            # The file will be reopened by the logging system on the next write
        super().emit(record)

class Logger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance._setup_logger()
        return cls._instance

    def _setup_logger(self):
        log_dir = "log"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        self.logger = logging.getLogger("ytdl_bot")
        self.logger.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Date-based Filename (yyyy-mm-dd.log) with automatic rotation
        handler = DailyFileHandler(log_dir)
        handler.setFormatter(formatter)

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        self.logger.addHandler(handler)
        self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger

# Global logger instance
logger = Logger().get_logger()
