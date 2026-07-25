"""Shared pytest fixtures and the Python-3.14 event-loop shim.

The shim mirrors main.py: Pyrogram 2.0.106 calls asyncio.get_event_loop() at
import time, and Python 3.14 no longer auto-creates a loop in the main thread.
It must run before any import that pulls in pyrogram (e.g. the sender).
"""

import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import pytest


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    """Point Config's writable dirs at a temp path."""
    from src.config import Config

    data = tmp_path / "data"
    downloads = tmp_path / "downloads"
    data.mkdir()
    downloads.mkdir()
    monkeypatch.setattr(Config, "DATA_DIR", str(data))
    monkeypatch.setattr(Config, "DOWNLOAD_DIR", str(downloads))
    # Keep the derived paths consistent with the temp DATA_DIR.
    monkeypatch.setattr(Config, "COOKIES_FILE", str(data / "cookies.txt"))
    monkeypatch.setattr(Config, "DB_PATH", str(data / "bot_database.db"))
    return tmp_path
