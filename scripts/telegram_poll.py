#!/usr/bin/env python3
"""
Daily Telegram stats push — runs once at 8am IST via GitHub Actions cron.
Sends channel stats proactively; makes exactly 1 YouTube API call per run.
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.services.telegram_service import TelegramService
from app.services.youtube_service import YouTubeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured, skipping")
        return
    if not settings.YOUTUBE_API_KEY or not settings.YOUTUBE_CHANNEL_HANDLE:
        logger.info("YouTube API key or channel handle not configured, skipping")
        return

    telegram = TelegramService(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
    yt = YouTubeService(
        client_id=settings.YOUTUBE_CLIENT_ID,
        client_secret=settings.YOUTUBE_CLIENT_SECRET,
        refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
    )

    try:
        stats = yt.get_channel_stats(
            api_key=settings.YOUTUBE_API_KEY,
            channel_handle=settings.YOUTUBE_CHANNEL_HANDLE,
        )
        msg = (
            f"📊 <b>Daily Channel Stats</b>\n\n"
            f"👥 Subscribers: <b>{stats['subscribers']:,}</b>\n"
            f"👁 Total Views: <b>{stats['views']:,}</b>\n"
            f"🎬 Videos: <b>{stats['videos']:,}</b>"
        )
        logger.info(f"Stats fetched: {stats}")
    except Exception as e:
        logger.error(f"Failed to fetch YouTube stats: {e}")
        msg = f"❌ Daily stats failed: {e}"

    await telegram.send(msg)


if __name__ == "__main__":
    asyncio.run(main())
