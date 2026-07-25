# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that downloads videos/posts and re-uploads them as native Telegram media. Built on Pyrogram (MTProto), so it can send files larger than the 50MB bot-API limit. Single videos are cached by source id in SQLite — repeat requests resend the stored Telegram `file_id` instead of re-downloading.

## Commands

Local iteration (fast, no image rebuild) is driven by the `Makefile`:

```bash
make install   # one-time: install runtime + dev deps into ./venv
make dev       # run locally with hot-reload (edit a .py -> auto-restart)
make run       # run locally once, no hot-reload
make prod      # build & (re)start the Docker stack (production)
make logs      # tail production bot logs
make stop      # docker compose down
pytest -q      # run the test suite (no creds/network needed)
```

`make dev`/`make run` start the `pot-provider` container (YouTube needs it) and **stop the dockerized prod bot first** — the same bot token can't run twice. They then run `python main.py` from `./venv`. Requires `ffmpeg` and `deno` on PATH locally (both needed for YouTube: transcode + JS-challenge solving). Both local dev and the Docker image run on `python:3.14`.

## Configuration

Env vars (loaded from `.env`) are centralized in `src/config.py`. Reading them is **side-effect free** — `Config.validate()` (exits if `TG_APP_ID`/`TG_API_HASH`/`TG_BOT_API` missing) and `Config.ensure_dirs()` are called explicitly from `main()`, not at import, so the package imports cleanly in tests without credentials. Env var names (`TG_*`) differ from attribute names (`API_ID`/`API_HASH`/`BOT_TOKEN`). `WHITE_LIST_IDS` is optional (empty = everyone). `DATA_DIR`/`DOWNLOAD_DIR`/`LOG_DIR` are env-overridable. Instagram/PO-token knobs (`POT_PROVIDER_URL`, `IG_PROXY_URL`, `IG_FIXER_URL`, `IG_OFFLOAD_BASE`, `IG_*_DOC_ID`) are optional with defaults — see `.env.example`.

## Architecture

The bot uses a **platform strategy pattern**. A URL is routed to the platform that `matches` it; each platform produces a normalized `Post`, and shared services do the downloading, processing, and sending.

Entry point `main.py`: event-loop shim (Pyrogram 2.0.106 calls `asyncio.get_event_loop()` at import; Python 3.14 needs a loop first — **the shim must stay before any pyrogram-importing import, including `src.container`**), then `Config.validate()`/`ensure_dirs()`, `container.db.initialize()`, and a Pyrogram `Client(plugins=dict(root="src.bot"), workdir=Config.DATA_DIR)`.

`src/container.py` is the **composition root** — it builds one shared instance of each service/platform/registry/orchestrator/`Database`. Both `main.py` and `src/bot/handlers.py` import the same `container`, so there's a single `Database` instance.

**Pyrogram plugin root:** only `@Client.on_message`-decorated functions under `src/bot/` are auto-registered. `src/bot/handlers.py` (the decorated, thin handlers) delegates to `container.orchestrator`; `src/bot/orchestrator.py` sits under the plugin root too but has no decorators, so it's just imported, not double-registered.

Layout:
- `src/platforms/` — `Platform` ABC (`base.py`) with `matches(url)`, `probe(url)->PostMeta`, `fetch(url, meta, status)->Post`. `ytdlp_base.py` (`YtDlpPlatform`) holds the shared yt-dlp probe/download/process flow; `youtube.py` adds the PO-token `extractor_args`, `pornhub.py` overrides `normalize_url` (shorties→`view_video`), `generic.py` is the catch-all. `instagram.py` is separate. `registry.py` resolves in order `[Instagram, PornHub, YouTube, Generic]` (Generic last).
- `src/services/` — `ytdlp.py` (`YtDlpClient`: format string, live cookiefile, per-call `extractor_args`, `last_extract_error`), `video.py` (`VideoProcessor`: H.264 transcode / thumbnail / probe + **dormant** PornHub-intro detection), `http.py` (`HttpClient`: curl_cffi impersonation + proxy), `instagram_client.py` (`InstagramClient`: the no-login fetch chain), `sender.py` (`TelegramSender`: single vs media-group send, returns `file_id`), `progress.py` (`UploadProgress`: per-upload state), `status.py` (`StatusReporter`).
- `src/bot/orchestrator.py` — `DownloadOrchestrator.handle_url`: resolve → `probe` → cache check (single videos only) → `fetch` → `send` → store `file_id` → cleanup in `finally`.
- `src/core/` — `models.py` (`MediaItem`, `PostMeta`, `Post`), `errors.py` (`PlatformError` hierarchy carrying the user-facing message).
- `src/storage/database.py` — `Database` (aiosqlite, single `videos` table). `src/utils/` — `logger.py`, `urls.py` (`clean_url`), `captions.py`.

**YouTube** needs a running PO-token provider (`pot-provider` container, `bgutil-ytdlp-pot-provider`) + Deno + `yt-dlp-ejs` to solve SABR/JS challenges and reach 1080p. Format prefers H.264 (avc1) + AAC capped at 1080p on the long edge (`width<=?1920][height<=?1920`, `?` keeps unknown-dimension formats). Non-H.264 downloads (VP9/AV1) are transcoded to H.264 for iOS.

**Instagram** is handled by `InstagramClient` with **no login/cookies/account** (yt-dlp/gallery-dl now require login for IG). Method chain (first with media wins): with `IG_PROXY_URL` set → mobile GraphQL → web GraphQL → api/v1; then always → the "fixer" (embed page for caption+carousel structure; video bytes from a public InstaFix offload host that serves from its own unblocked IP, since the user's server IP is blocked by Instagram); then embed-only (images+caption). The whole post is sent as a media group (chunked to 10) with the caption on the first item.

**PornHub intro removal** is implemented (`VideoProcessor._detect_intro`, audio cross-correlation vs `assets/ph_community_intro.wav`) but **disabled** — trimming forces a full re-encode that is far too slow on long videos. `VideoProcessor._process` hardcodes `trim=0.0`.

## Testing

`pytest` + `pytest-asyncio` (`asyncio_mode=auto`, `pythonpath=.` in `pytest.ini`). All tests run **without credentials or network** — `tests/conftest.py` runs the event-loop shim and provides `tmp_dirs`/`fake_message` fixtures; external IO is faked/monkeypatched (`FakeHttp` for Instagram, `yt_dlp.YoutubeDL` and `subprocess.run` monkeypatched, `FakeClient` for Pyrogram). Coverage: URL routing, `clean_url`/captions, PornHub normalization, Instagram parsers on synthetic fixtures, yt-dlp client, video processor, sender, progress throttling, and orchestrator cache/error/cleanup flow.

## Gotchas

- **Instagram video needs a non-blocked IP.** The user's server IP is blocked by Instagram for direct video endpoints; the fixer host works around it but depends on that third-party service (hosts are env-overridable).
- **`VideoProcessor._process` deletes its source** and returns `*_proc.mp4`; `Post` holds only the processed path, and cleanup guards with `os.path.exists`.
- Instagram posts are never cached (`supports_cache=False`) and single IG videos are sent without an upload progress bar.
