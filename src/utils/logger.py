"""Module-level `logger` used across the bot: console + one file per day.

Nothing is created or opened at import time (no mkdir, no open file) so importing
the package stays side-effect free, just like src.config. Note src.config must not
import this module — that would be an import cycle.
"""

import logging
import os
from datetime import datetime

from src.config import Config

_LOGGER_NAME = "ytdl_bot"
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class DailyFileHandler(logging.FileHandler):
    def __init__(self, log_dir, encoding="utf-8"):
        self.log_dir = log_dir
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        # delay=True: the file is only opened on the first record, so importing the
        # module never touches the filesystem.
        super().__init__(self._path(), encoding=encoding, delay=True)

    def _path(self):
        return os.path.join(self.log_dir, f"{self.current_date}.log")

    def _open(self):
        # Config.ensure_dirs() may not have run yet (or the dir may have been wiped).
        os.makedirs(self.log_dir, exist_ok=True)
        return super()._open()

    def emit(self, record):
        new_date = datetime.now().strftime("%Y-%m-%d")
        if new_date != self.current_date:
            self.current_date = new_date
            self.baseFilename = os.path.abspath(self._path())
            self.close()
            # The file will be reopened by the logging system on the next write
        super().emit(record)


def _build_logger():
    log = logging.getLogger(_LOGGER_NAME)
    if log.handlers:  # module re-initialised (e.g. reload) — don't duplicate output
        return log

    # getattr instead of setLevel(str): an unknown/lowercase LOG_LEVEL must not
    # make importing the logger explode.
    log.setLevel(getattr(logging, str(Config.LOG_LEVEL).upper(), logging.INFO))
    formatter = logging.Formatter(_FORMAT)

    # Date-based Filename (yyyy-mm-dd.log) with automatic rotation
    file_handler = DailyFileHandler(Config.LOG_DIR)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    log.addHandler(file_handler)
    log.addHandler(console_handler)
    return log


logger = _build_logger()
