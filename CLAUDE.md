# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that downloads videos/posts and re-uploads them as native Telegram media. Built on Pyrogram (MTProto), so it can send files larger than the 50MB bot-API limit. Single videos are cached by `(platform, source id)` in SQLite — repeat requests resend the stored Telegram `file_id` instead of re-downloading.

**Product invariants** — judge changes against these, not just against generic best practice:
- One unified interface per service: a URL routes to a `Platform` that returns a normalized `Post`; shared services download, process, and send.
- A message does not have to *be* a link: every link in a forwarded post is found and every media one is downloaded.
- Every platform shows a **download** progress bar (service → server) *and* an **upload** progress bar (server → Telegram).
- Every post carries a caption whose title links back to the source, with tracking params stripped.

## Code style

**Comment sparingly.** A comment earns its place only by saying what the code cannot: a non-obvious *why*, a constraint imposed from outside, a trap someone would otherwise re-introduce. Reviewers here read comments as claims to verify, so noise costs more than it gives.

- Never restate the line below it, and never narrate a step (`# download the file`).
- No docstring on a short function whose name and signature already say it. One line when it does need one.
- A multi-line docstring is for an invariant or trade-off that would otherwise be lost — not for prose about how the function works.
- If the explanation is longer than the code, it belongs in this file (architecture, gotchas), not inline.
- Match the comment density of the file being edited, and leave comments in untouched code alone.

## Commands

Local iteration (fast, no image rebuild) is driven by the `Makefile`:

```bash
make install   # one-time: install runtime + dev deps into ./venv
make dev       # run locally with hot-reload (edit a .py -> auto-restart)
make run       # run locally once, no hot-reload
make prod      # build & (re)start the Docker stack (production)
make logs      # tail production bot logs
make stop      # docker compose down
pytest -q      # offline test suite (no creds/network needed)
RUN_NETWORK_TESTS=1 pytest -q -m network    # opt-in live-URL suite (see Testing)
RUN_TELEGRAM_TESTS=1 pytest -q -m telegram  # opt-in real uploads to a dev bot
```

`make dev`/`make run` start the `pot-provider` container (YouTube needs it) and **stop the dockerized prod bot first** — the same bot token can't run twice. They then run `python main.py` from `./venv`. Requires `ffmpeg` and `deno` on PATH locally (both needed for YouTube: transcode + JS-challenge solving). Both local dev and the Docker image run on `python:3.14`.

## Configuration

`src/config.py` is the **single source of truth** — no other module reads `os.environ`; a stray `os.getenv` outside it is a bug. Reading env values is **side-effect free** (no exit, no mkdir): `Config.validate()` (exits if `TG_APP_ID`/`TG_API_HASH`/`TG_BOT_API` missing) and `Config.ensure_dirs()` are called explicitly from `main()`, not at import, so the package imports cleanly in tests without credentials.

Env var names (`TG_*`) differ from attribute names (`API_ID`/`API_HASH`/`BOT_TOKEN`). `WHITE_LIST_IDS` is optional (empty = everyone). `DATA_DIR`/`DOWNLOAD_DIR`/`LOG_DIR`/`LOG_LEVEL` are env-overridable. `MAX_CONCURRENT_DOWNLOADS` (default 2) caps parallel download+transcode work. `RETRY_ATTEMPTS` (default 3) / `RETRY_DELAY` (default 2.0s) drive the orchestrator's transient-failure retries (`RETRY_ATTEMPTS=1` disables them). Instagram/PO-token knobs (`POT_PROVIDER_URL`, `IG_PROXY_URL`, `IG_FIXER_URL`, `IG_OFFLOAD_BASE`, `IG_*_DOC_ID`) are optional with defaults — see `.env.example`.

## Architecture

The bot uses a **platform strategy pattern**. A URL is routed to the platform that `matches` it; each platform produces a normalized `Post`, and shared services do the downloading, processing, and sending.

Entry point `main.py`: event-loop shim (Pyrogram 2.0.106 calls `asyncio.get_event_loop()` at import; Python 3.14 needs a loop first — **the shim must stay before any pyrogram-importing import, including `src.container`**), then `Config.validate()`/`ensure_dirs()`, `sweep_downloads()` (drops work dirs orphaned by a previous SIGKILL), `container.db.initialize()`, and a Pyrogram `Client(plugins=dict(root="src.bot"), workdir=Config.DATA_DIR)`. Shutdown calls `app.stop()` so the MTProto session closes cleanly.

`src/container.py` is the **composition root** — it builds one shared instance of each service/platform/registry/orchestrator/`Database`. Both `main.py` and `src/bot/handlers.py` import the same `container`, so there's a single `Database` instance. Because services are shared across concurrent requests, **they must not hold per-request state** — return failure reasons to the caller instead of parking them on `self`.

**Pyrogram plugin root:** only `@Client.on_message`-decorated functions under `src/bot/` are auto-registered. `src/bot/handlers.py` (the decorated, thin handlers) delegates to `container.orchestrator`; `src/bot/orchestrator.py` sits under the plugin root too but has no decorators, so it's just imported, not double-registered.

Layout:
- `src/platforms/` — `Platform` ABC (`base.py`) with `matches(url)`, `is_media_link(url)` (defaults to `matches`; see **Link scanning**), `probe(url)->PostMeta`, `fetch(url, meta, status, work_dir)->Post`. `ytdlp_base.py` (`YtDlpPlatform`) is the **abstract** shared yt-dlp probe/download/process flow (not registrable on its own); `youtube.py` adds the PO-token `extractor_args`, `pornhub.py` overrides `normalize_url` (shorties→`view_video`), `generic.py` is the concrete catch-all. `instagram.py` is separate. `registry.py` resolves in order `[Instagram, PornHub, YouTube, Generic]` (Generic last), answers `is_media_link(url)` by delegating to the owning platform, and exposes a read-only `platforms` view.
- `src/services/` — `ytdlp.py` (`YtDlpClient`: format string, live cookiefile, per-call `extractor_args`; `extract_info` returns `(info, error)` and `download` returns `(path, info, error)` — stateless, plus `is_auth_error()` for the login-wall heuristic), `video.py` (`VideoProcessor`: H.264 transcode / thumbnail / probe), `http.py` (`HttpClient`: curl_cffi impersonation, `has_proxy` property, streaming `download(..., on_progress)` that never buffers a whole file in RAM), `instagram_client.py` (`InstagramClient`: the no-login fetch chain), `sender.py` (`TelegramSender`: single vs media-group send, returns `file_id`; a single video always gets an `UploadProgress` — Pyrogram 2.0.106's `send_media_group` takes no progress callback, so a group upload can only announce that it started), `progress.py` (`_ThreadedProgress` base doing the worker-thread→loop hop; `DownloadProgress` for yt-dlp hooks, `FileDownloadProgress` for byte callbacks, `UploadProgress` for Pyrogram), `status.py` (`StatusReporter`).
- `src/bot/orchestrator.py` — `DownloadOrchestrator.handle_url`: resolve → `probe` → cache check (single videos only) → create per-request work dir → `fetch` under a semaphore → `send` → store `file_id` → `rmtree(work_dir)` in `finally`. Each of those network steps runs through `_retrying` (see **Retries**).
- `src/core/` — `models.py` (`MediaItem`, `PostMeta`, `Post`), `errors.py` (`PlatformError` hierarchy carrying the user-facing message).
- `src/storage/database.py` — `Database` (aiosqlite, single `videos` table): `get_file_id(platform, video_id)` / `add_file_id(platform, video_id, file_id, title)` (upsert, so a re-download replaces an invalidated `file_id`). `initialize()` also migrates a pre-composite-key DB in one transaction. `src/utils/` — `logger.py` (module-level `logger`, console + one file per day, nothing opened at import), `urls.py` (`clean_url`, `is_http_url`), `captions.py`.

**Per-request work dir.** The orchestrator creates `DOWNLOAD_DIR/<uuid hex[:12]>` *after* the cache check and `shutil.rmtree`s it unconditionally in `finally`. Every platform must write inside the `work_dir` it is handed. This is what keeps concurrent requests for the same video from colliding on one output path, and what stops a `fetch` that raises halfway from leaking partial files.

**Link scanning.** A handler works on any text/caption message, not only on one that *is* a URL: `extract_urls(text, extra)` (`src/utils/urls.py`) regex-scans the text, trims sentence/markdown punctuation (a closing bracket is kept when it has an opener), merges Telegram's hidden `text_link` hrefs (`_hidden_urls` in `handlers.py` — only entities carrying a `url`, which sidesteps UTF-16 entity offsets entirely) and dedupes. `_targets()` then decides what to act on: **links a platform recognizes as media**, or — when none do — a lone link taken at face value, so an exotic site keeps working the way a pasted link always has. Everything else in a post (the source article, the `t.me/channel` subscribe link) is dropped silently, since acting on it would mean an error message per unrelated link. `GenericPlatform.is_media_link` is what makes that distinction possible: it defers to `has_dedicated_extractor(url)` (`services/ytdlp.py`), which asks yt-dlp's ~1700 site extractors — all but the catch-all `Generic` — offline, by regex, and caches the class list on first use. Multiple targets are handled sequentially, each with its own status message.

**Retries.** `DownloadOrchestrator._retrying(operation, ...)` takes a *coroutine factory* and re-runs it up to `Config.RETRY_ATTEMPTS` times, `Config.RETRY_DELAY` seconds apart, announcing each retry in the status message. It wraps `probe`, `fetch` (including the "post has no media" check, so an empty result retries like a raised error), and `send_post` — so every platform gets retries from the shared layer rather than implementing its own. Any exception is treated as transient **except** `_PERMANENT_ERRORS` (`AuthRequiredError`: a login wall is a verdict, and retrying only delays the message). Two invariants make a retry safe: the work dir is emptied in place between fetch attempts (`_reset_dir` — yt-dlp resumes a `.part`, so a truncated fragment would otherwise be inherited by the retry), and the download semaphore is released across the wait, so a sleeping request never blocks a queued one. This sits *above* `YtDlpClient._download`'s own single 403 re-extraction — the two compose deliberately.

**Concurrency.** Download+transcode runs under `asyncio.Semaphore(Config.MAX_CONCURRENT_DOWNLOADS)` owned by the single orchestrator (waiting users see a "Queued" status). The Telegram upload is deliberately outside the semaphore — it's network bound.

**Metadata flow.** `probe` returns a `PostMeta` used for the cache lookup; `fetch` refines it with `dataclasses.replace` and puts the result on `Post.meta`. The orchestrator captions and caches from `post.meta`, never from its own probe result — don't reintroduce in-place mutation across that boundary.

**YouTube** needs a running PO-token provider (`pot-provider` container, `bgutil-ytdlp-pot-provider`) + Deno + `yt-dlp-ejs` to solve SABR/JS challenges and reach 1080p. Format prefers H.264 (avc1) + AAC capped at 1080p on the long edge (`width<=?1920][height<=?1920`, `?` keeps unknown-dimension formats). Non-H.264 downloads (VP9/AV1) are transcoded to H.264 for iOS.

**Instagram** is handled by `InstagramClient` with **no login/cookies/account** (yt-dlp/gallery-dl now require login for IG). Method chain (first with media wins): with `IG_PROXY_URL` set → mobile GraphQL → web GraphQL → api/v1; then always → the "fixer" (embed page for caption+carousel structure; video bytes from a public InstaFix offload host that serves from its own unblocked IP, since the user's server IP is blocked by Instagram); then embed-only (images+caption). Multi-item posts are sent as a media group (chunked to 10) with the caption on the first item; a single-item post is sent as a single photo/video and gets the same upload progress bar as every other platform.

## Testing

`pytest` + `pytest-asyncio` (`asyncio_mode=auto`, `pythonpath=.` in `pytest.ini`). Three tiers — each higher tier is opt-in twice over (a marker *and* an env var), so a plain `pytest` and any CI run stay offline:

1. **Offline (default, `pytest -q`)** — no credentials, no network, no `.env`. `tests/conftest.py` runs the event-loop shim and provides the `tmp_dirs` fixture; `tests/fakes.py` holds the canonical doubles (`FakeStatus`, `FakeStatusMessage`, `FakeChatMessage`, `FakeTelegramClient`) — reuse them instead of declaring another local fake. External IO is faked/monkeypatched (`FakeHttp` for Instagram, `yt_dlp.YoutubeDL` and `subprocess.run` monkeypatched).
2. **Live services (`RUN_NETWORK_TESTS=1 pytest -q -m network`)** — `tests/test_live_urls.py` probes each link for metadata and asserts title/duration/dimensions and that orientation matches the declared format. A test also fails if a registered platform has no row.
3. **Real uploads (`RUN_TELEGRAM_TESTS=1 pytest -q -m telegram`)** — `tests/test_telegram_send.py` posts to a **dev** bot (`TG_TEST_BOT_TOKEN` + `TG_TEST_CHAT_ID` in `.env`; the fixture fails outright if the token equals `TG_BOT_API`, and a bot can't open a conversation, so press Start on it first). The only tier that can prove Telegram *accepts* what the bot produced. Two halves: **sender cases** on ffmpeg-generated media (caption HTML parses into a `text_link` at the cleaned URL, a vertical clip comes back vertical, a stored `file_id` resends with the source file deleted, an album captions only its first item and chunks at 10) and **`test_pipeline_end_to_end`, parametrized over every `e2e=True` row** — YouTube landscape + Shorts, PornHub shorties, VK landscape + clip, Instagram reel + carousel + photo — each taken through probe → download → process → upload → cache row → work-dir cleanup against the **production** `container.registry`. Messages are left in the chat on purpose; `TG_TEST_CLEANUP=1` deletes them.

**The link table lives in `tests/live_links.py`**, not in a test: all three tiers read the same rows, so a real link exists in exactly one place. A `Link` carries what it must prove (`orientation`, `media_types`, `normalized`, `shortcode`) and which tiers use it (`live_probe`, `e2e`). Adding a service is a row, not a test; e2e rows are kept to short clips (9–22s) because that tier really downloads and uploads them. Live links rot — replace a dead one there.

Missing infrastructure **skips** with a reason instead of failing — a live test may only go red when the code is wrong. Those probes live in `tests/live_env.py` (`tcp_reachable`, `skip_unless_youtube_env_ready`, `skip_unless_ffmpeg`), shared by both live tiers.

Coverage: URL routing, `is_media_link` per host, `clean_url`/captions/`is_http_url`/`extract_urls`, handler whitelist + forwarded-post link scanning, PornHub normalization, Instagram parsers on synthetic fixtures, yt-dlp client, video processor, sender, progress throttling, `Database` (composite key + migration), and orchestrator cache/error/cleanup/concurrency/retry flow (`_orch` in `tests/test_orchestrator.py` passes `retry_delay=0`, so only the timing test actually waits).

## Gotchas

- **Instagram video needs a non-blocked IP.** The user's server IP is blocked by Instagram for direct video endpoints; the fixer host works around it but depends on that third-party service (hosts are env-overridable).
- **A retried upload can, in principle, post twice** — if Telegram accepted the file but the confirmation never came back. Judged rarer than a dropped upload and cheaper than making the user resend the link; a retried upload deliberately reuses the files on disk instead of re-downloading.
- **`VideoProcessor._process` deletes its source** and returns `*_proc.mp4`; `Post` holds only the processed path. Cleanup is the work-dir `rmtree`, so this is invisible to callers.
- Instagram posts are never cached (`supports_cache=False`).
- **A YouTube 403 on download is retried once with a fresh extraction** (`YtDlpClient._download`). Signed media URLs go stale — used a moment late or under bursty access they answer `HTTP Error 403`, and yt-dlp's own `retries` re-requests the same dead URL. Only re-extracting yields freshly signed ones. Real failures (video unavailable, login-gated) are not retried, so a dead link still fails fast.
- **yt-dlp extracts metadata twice per request** (`probe` with `download=False`, then `download` with `download=True`) — 2× network and 2× PO-token cost. Tolerated deliberately: the only fix is `ydl.process_ie_result`, which can't be verified offline. See the note in `YtDlpClient._download`.
- **PornHub intro removal was removed** (audio cross-correlation against a reference bumper): trimming forces a full re-encode that is far too slow on long videos. Recoverable from git history (commits `9f780aa` / `1de6158`).
- Architecture re-audits: `.claude/agents/architecture-audit.md` defines a read-only auditor agent with the full checklist. Invoke it before a refactor or after adding a platform.
