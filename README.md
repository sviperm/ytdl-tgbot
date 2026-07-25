# Telegram YTDL Bot

A professional, high-performance Telegram bot built with [Pyrogram](https://github.com/pyrogram/pyrogram) and [yt-dlp](https://github.com/yt-dlp/yt-dlp) to download videos from any supported platform (YouTube, VK, Vimeo, etc.) and send them as native Telegram video files.

## Features

- 🚀 **High Speed**: Built with Python and MTProto for maximum performance.
- 📁 **Large File Support**: Supports uploading files larger than 50MB using official MTProto credentials.
- 💾 **Caching Engine**: Built-in SQLite database to cache already downloaded videos.
- 📊 **Progress Monitoring**: Real-time upload progress bars with MB/s and ETA.
- 🔒 **Whitelisting**: Optional security to restrict the bot to specific users.
- 📅 **Daily Logging**: Robust logging system with daily rotation.
- 🍪 **Cookie Support**: Supports `cookies.txt` for age-restricted or region-locked content.

## Installation

### Prerequisites

- Python 3.8+
- [FFmpeg](https://ffmpeg.org/) installed on your system.
- Telegram `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org).
- Bot Token from [@BotFather](https://t.me/BotFather).

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/ytdl-tgbot.git
   cd ytdl-tgbot
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the environment**:
   Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

4. **Add cookies (Optional)**:
   Place your `cookies.txt` in the root directory if you need to download restricted content.

### Running

```bash
python main.py
```

## Deployment with Docker

The easiest way to run the bot is using Docker and Docker Compose.

1. **Configure the environment**:
   Ensure you have a `.env` file with your credentials.

2. **Build and start**:
   ```bash
   docker-compose up -d --build
   ```

3. **Check logs**:
   ```bash
   docker-compose logs -f
   ```

4. **Stop the bot**:
   ```bash
   docker-compose down
   ```

## Configuration

The bot can be restricted using the `WHITE_LIST_IDS` variable in the `.env` file:
- `WHITE_LIST_IDS="12345678,87654321"` - Only these users can use the bot.
- `WHITE_LIST_IDS=""` - Everyone can use the bot.

## Testing

The suite runs in three tiers. Each higher tier is opt-in twice over — a marker
*and* an environment variable — so a plain `pytest` never touches the network.

1. **Offline (default)**: no credentials, no network, no `.env` needed.
   ```bash
   pytest -q
   ```
   Everything external is faked. The live tests report as skipped.

2. **Live (opt-in)**: probes the real services with the table of real links in
   `tests/test_live_urls.py` — one row per service and per format (horizontal
   video and vertical shorts/reels).
   ```bash
   RUN_NETWORK_TESTS=1 ./venv/bin/pytest -q -m network
   ```
   Metadata only, never a full download, so it finishes in seconds. It needs:
   - the PO-token provider for YouTube: `docker compose up -d pot-provider`
   - [Deno](https://deno.com/) on `PATH` (YouTube's JS challenge)
   - an IP Instagram does not block, or `IG_PROXY_URL` in `.env`

   Anything missing from the environment is skipped with the reason, not failed.

3. **Real uploads (opt-in)**: sends actual media to a **dev** bot, which is the
   only way to prove Telegram accepts what the bot produces — that the caption
   HTML parses, that a vertical video stays vertical, that a cached `file_id`
   resends, that an album chunks at 10. It also runs the **whole pipeline per
   service** — YouTube (landscape + Shorts), PornHub shorties, VK (video + clip),
   Instagram (reel, carousel, photo) — from link to delivered message.
   ```bash
   RUN_TELEGRAM_TESTS=1 ./venv/bin/pytest -q -m telegram
   ```
   Add to `.env` (never the production bot — these post real messages):
   ```
   TG_TEST_BOT_TOKEN="<a second bot from @BotFather>"
   TG_TEST_CHAT_ID="<your user id>"
   ```
   Press **Start** on the dev bot first: a bot cannot open a conversation, so
   without it every send fails with `PEER_ID_INVALID`. `ffmpeg` generates the test
   media at run time, so no fixtures are committed. Messages are left in the chat
   so you can look at them; `TG_TEST_CLEANUP=1` deletes them instead.

Live links rot. When one dies, replace it in the table in `tests/live_links.py` —
all three tiers read that one table, and adding a new platform without a row there
fails the suite.

## Project Structure

```text
.
├── src/
│   ├── bot/         # Telegram message handlers
│   ├── database/    # SQLite caching logic
│   ├── downloader/  # yt-dlp wrapper
│   ├── utils/       # Logger and helpers
│   └── config.py    # Configuration loader
├── log/             # Daily rotating logs
├── downloads/       # Temporary download folder
├── main.py          # Entry point
└── LICENSE          # MIT License
```

## License

This project is licensed under the [MIT License](LICENSE).
