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


def test_parse_int():
    from src.config import _parse_int

    assert _parse_int("7") == 7
    assert _parse_int(" 7 ") == 7
    assert _parse_int("abc", 3) == 3
    assert _parse_int(None, 3) == 3
    assert _parse_int("") == 0


def test_instagram_defaults(monkeypatch):
    # Same isolated-exec trick as above: no env, so we see the baked-in defaults.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    for var in ("IG_PROXY_URL", "IG_FIXER_URL", "IG_OFFLOAD_BASE",
                "IG_MOBILE_DOC_ID", "IG_WEB_DOC_ID", "LOG_LEVEL",
                "MAX_CONCURRENT_DOWNLOADS"):
        monkeypatch.delenv(var, raising=False)
    source = open(os.path.join("src", "config.py")).read()
    namespace = {}
    exec(compile(source, "src/config.py", "exec"), namespace)
    cfg = namespace["Config"]

    assert cfg.IG_PROXY_URL == ""
    assert cfg.IG_FIXER_URL == "https://www.instagram7.com"
    assert cfg.IG_MOBILE_DOC_ID == "8845758582119845"
    assert cfg.IG_WEB_DOC_ID == "25531498899829322"
    assert cfg.LOG_LEVEL == "INFO"
    assert cfg.MAX_CONCURRENT_DOWNLOADS == 2
    # the offload base is derived from the fixer host, not hardcoded separately
    assert cfg.IG_OFFLOAD_BASE == cfg.IG_FIXER_URL + "/offload"


def test_fixer_url_trailing_slash_stripped_and_offload_follows(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("IG_FIXER_URL", "https://other.example/")
    monkeypatch.delenv("IG_OFFLOAD_BASE", raising=False)
    source = open(os.path.join("src", "config.py")).read()
    namespace = {}
    exec(compile(source, "src/config.py", "exec"), namespace)
    cfg = namespace["Config"]

    assert cfg.IG_FIXER_URL == "https://other.example"
    assert cfg.IG_OFFLOAD_BASE == "https://other.example/offload"
