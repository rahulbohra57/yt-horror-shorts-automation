#!/usr/bin/env python3
"""
One-shot Telegram poll: fetch pending messages, reply to STATS commands.
Designed to be called from GitHub Actions after each pipeline run.
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from app.core.config import settings
from app.services.telegram_service import TelegramService
from app.services.youtube_service import YouTubeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_GET_UPDATES = "https://api.telegram.org/bot{token}/getUpdates"
TELEGRAM_SET_OFFSET = "https://api.telegram.org/bot{token}/getUpdates?offset={offset}"
OFFSET_FILE = Path(ROOT / ".data" / "tg_offset.txt")


def _load_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))


async def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not set, skipping poll")
        return

    telegram = TelegramService(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
    offset = _load_offset()

    async with httpx.AsyncClient(timeout=15) as client:
        url = TELEGRAM_SET_OFFSET.format(token=settings.TELEGRAM_BOT_TOKEN, offset=offset) if offset else \
              TELEGRAM_GET_UPDATES.format(token=settings.TELEGRAM_BOT_TOKEN)
        resp = await client.get(url)
        data = resp.json()

    updates = data.get("result", [])
    if not updates:
        logger.info("No pending Telegram updates")
        return

    logger.info(f"Processing {len(updates)} Telegram updates")
    last_update_id = offset

    for update in updates:
        update_id = update.get("update_id", 0)
        last_update_id = max(last_update_id, update_id)

        message = update.get("message", {})
        text = (message.get("text") or "").strip().upper()
        chat_id = message.get("chat", {}).get("id")

        if not chat_id or text != "STATS":
            continue

        logger.info(f"STATS requested by chat_id={chat_id}")
        if not settings.YOUTUBE_API_KEY or not settings.YOUTUBE_CHANNEL_HANDLE:
            await telegram.reply(chat_id, "❌ YouTube API key or channel handle not configured.")
            continue

        try:
            yt = YouTubeService(
                client_id=settings.YOUTUBE_CLIENT_ID,
                client_secret=settings.YOUTUBE_CLIENT_SECRET,
                refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
            )
            stats = yt.get_channel_stats(
                api_key=settings.YOUTUBE_API_KEY,
                channel_handle=settings.YOUTUBE_CHANNEL_HANDLE,
            )
            msg = (
                f"📊 <b>Channel Stats</b>\n\n"
                f"👥 Subscribers: <b>{stats['subscribers']:,}</b>\n"
                f"👁 Total Views: <b>{stats['views']:,}</b>\n"
                f"🎬 Videos: <b>{stats['videos']:,}</b>"
            )
        except Exception as e:
            logger.error(f"Failed to fetch stats: {e}")
            msg = f"❌ Could not fetch stats: {e}"

        await telegram.reply(chat_id, msg)

    # Advance offset so we don't re-process these updates
    _save_offset(last_update_id + 1)
    logger.info(f"Offset advanced to {last_update_id + 1}")


if __name__ == "__main__":
    asyncio.run(main())
