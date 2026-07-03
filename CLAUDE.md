# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that downloads videos via `yt-dlp` and re-uploads them as native Telegram videos. Built on Pyrogram (MTProto), so it can send files larger than the 50MB bot-API limit. Downloads are cached by source video ID in SQLite — repeat requests resend the cached Telegram `file_id` instead of re-downloading.

## Commands

Local iteration (fast, no image rebuild) is driven by the `Makefile`:

```bash
make install   # one-time: install runtime + dev deps into ./venv
make dev       # run locally with hot-reload (edit a .py -> auto-restart)
make run       # run locally once, no hot-reload
make prod      # build & (re)start the Docker stack (production)
make logs      # tail production bot logs
make stop      # docker compose down
```

`make dev`/`make run` start the `pot-provider` container (YouTube needs it) and
**stop the dockerized prod bot first** — the same bot token can't run twice. They
then run `python main.py` from `./venv`. Requires `ffmpeg` and `deno` on PATH
locally (both needed for YouTube: transcode + JS-challenge solving).

There is no test suite or linter. Both local dev and the Docker image run on
`python:3.14`.

## Configuration

All config comes from environment variables (loaded from `.env` via python-dotenv) and is centralized in `src/config.py`. Required: `TG_APP_ID`, `TG_API_HASH`, `TG_BOT_API` — the process exits at import time if any is missing. Optional `WHITE_LIST_IDS` is a comma-separated list of Telegram user IDs; empty means everyone is allowed. Note the env var names (`TG_*`) differ from the `Config` attribute names (`API_ID`, `API_HASH`, `BOT_TOKEN`).

`src/config.py` also creates the `downloads/` and `log/` directories as a side effect of import, and hardcodes `DB_PATH`, `DOWNLOAD_DIR`, and `COOKIES_FILE`.

## Architecture

Entry point `main.py` initializes the database, constructs the Pyrogram `Client` with `plugins=dict(root="src.bot")`, and idles forever. Because of the plugin root, **any `@Client.on_message` handler in `src/bot/` is auto-registered** — `src/bot/handlers.py` is loaded by Pyrogram's plugin system, not imported by `main.py`.

Request flow (in `src/bot/handlers.py`, `video_link_handler`):
1. Whitelist check, then verify the message text is an `http(s)` URL.
2. `downloader.extract_info(url)` pulls metadata (id, extractor, title, duration, dimensions) without downloading.
3. Look up `video_id` in the DB. On a cache hit, resend the stored `file_id` directly. If that send fails (stale `file_id`), fall through to re-download.
4. `downloader.download(url)` downloads to `downloads/`, then `client.send_video(...)` uploads with a live progress callback.
5. On success, store `(video_id, platform, file_id, title)` in the DB and delete the local file in a `finally` block.

After download, `handlers.py` calls `downloader.process_video()`, which trims a detected **PornHub "Community" intro** and/or transcodes to H.264 in one ffmpeg pass (H.264 files with no intro are returned untouched — no wasteful re-encode). The intro is detected by normalized audio cross-correlation (numpy) against the bundled reference `assets/ph_community_intro.wav` — only that fixed bumper is removed (not sponsor ads like the 1win insert). The trimmed duration is re-probed so Telegram shows the correct length.

`src/downloader/ytdl.py` (`Downloader`) wraps `yt-dlp`. Blocking yt-dlp calls run via `asyncio.to_thread` to avoid blocking the event loop. Format is `bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best` (requires ffmpeg to merge). YouTube uses the `android`/`ios` player clients. `cookies.txt` in the repo root, if present, is passed to yt-dlp for restricted content. After a merge the output extension can change, so `_download` falls back to scanning `DOWNLOAD_DIR` for a file matching the video id.

`src/database/models.py` (`Database`) is async (`aiosqlite`) with a single `videos` table. Each method opens and closes its own connection. `add_video` uses `INSERT OR IGNORE` on the unique `video_id`.

`src/utils/logger.py` exposes a singleton `logger` writing to both console and `log/YYYY-MM-DD.log`, with the `DailyFileHandler` rotating the filename on date change.

## Gotchas

- **Upload progress uses module-level globals** (`last_update_time` in `handlers.py`). This is not concurrency-safe — simultaneous uploads from different users will interleave their progress state.
- `Database()` is instantiated separately in both `main.py` and `handlers.py`; only `main.py`'s instance runs `initialize()`. This works because every method opens its own connection, but the two objects are distinct.
- `extract_info` is called before download and its dimensions are used for the cached-send path; the post-download `info` can override width/height/duration if they changed.
