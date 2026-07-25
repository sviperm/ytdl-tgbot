"""Config must import without side effects and validate lazily."""

import os

import pytest


def test_import_body_no_exit_without_creds(monkeypatch):
    # Run the module body in isolation with no credentials and no .env loading;
    # it must NOT raise SystemExit (the old code called sys.exit at import).
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    for var in ("TG_APP_ID", "TG_API_HASH", "TG_BOT_API"):
        monkeypatch.delenv(var, raising=False)
    source = open(os.path.join("src", "config.py")).read()
    namespace = {}
    exec(compile(source, "src/config.py", "exec"), namespace)  # must not exit
    assert namespace["Config"].API_ID == 0
    assert namespace["Config"].BOT_TOKEN == ""


def test_validate_raises_without_credentials(monkeypatch):
    from src.config import Config

    monkeypatch.setattr(Config, "API_ID", 0)
    monkeypatch.setattr(Config, "API_HASH", "")
    monkeypatch.setattr(Config, "BOT_TOKEN", "")
    with pytest.raises(SystemExit):
        Config.validate()


def test_validate_passes_with_credentials(monkeypatch):
    from src.config import Config

    monkeypatch.setattr(Config, "API_ID", 123)
    monkeypatch.setattr(Config, "API_HASH", "hash")
    monkeypatch.setattr(Config, "BOT_TOKEN", "token")
    Config.validate()  # should not raise


def test_ensure_dirs_creates_directories(tmp_path, monkeypatch):
    from src.config import Config

    monkeypatch.setattr(Config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(Config, "DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setattr(Config, "LOG_DIR", str(tmp_path / "log"))
    Config.ensure_dirs()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "downloads").is_dir()
    assert (tmp_path / "log").is_dir()


def test_whitelist_parsing():
    from src.config import _parse_whitelist

    assert _parse_whitelist("111, 222 ,333") == [111, 222, 333]
    assert _parse_whitelist("") == []
    assert _parse_whitelist("abc, 42, ") == [42]
