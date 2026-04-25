#!/usr/bin/env python3
"""
Telegram command handler — runs every 30 minutes via GitHub Actions.
Handles: CREATE HORROR, CREATE MYSTERY
Triggers the scheduled_uploads.yml workflow via GitHub API.
Only uses Telegram API (free, no YouTube quota consumed).
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from app.core.config import settings
from app.services.telegram_service import TelegramService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VALID_GENRES = {"horror", "mystery"}
OFFSET_FILE = Path(ROOT / ".data" / "tg_cmd_offset.txt")
GET_UPDATES = "https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=5"


def _load_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))


async def _dispatch_pipeline(genre: str, github_token: str, repo: str) -> bool:
    """Trigger scheduled_uploads.yml workflow via GitHub API."""
    url = f"https://api.github.com/repos/{repo}/actions/workflows/scheduled_uploads.yml/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main", "inputs": {"niche": genre, "upload": "true"}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code == 204:
        logger.info(f"Pipeline dispatched for genre={genre}")
        return True
    logger.error(f"Dispatch failed: {resp.status_code} {resp.text}")
    return False


async def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not set, skipping")
        return

    github_token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not github_token or not repo:
        logger.error("GITHUB_TOKEN or GITHUB_REPOSITORY not set")
        return

    telegram = TelegramService(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
    offset = _load_offset()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(GET_UPDATES.format(token=settings.TELEGRAM_BOT_TOKEN, offset=offset))
        data = resp.json()

    updates = data.get("result", [])
    if not updates:
        logger.info("No pending commands")
        return

    logger.info(f"Processing {len(updates)} updates")
    last_update_id = offset - 1

    for update in updates:
        update_id = update.get("update_id", 0)
        last_update_id = max(last_update_id, update_id)

        message = update.get("message", {})
        raw_text = (message.get("text") or "").strip()
        chat_id = message.get("chat", {}).get("id")
        text = raw_text.upper()

        if not chat_id or not text.startswith("CREATE"):
            continue

        parts = text.split()
        if len(parts) < 2 or parts[1].lower() not in VALID_GENRES:
            await telegram.reply(
                chat_id,
                f"❓ Unknown genre. Use:\n<code>CREATE HORROR</code>\n<code>CREATE MYSTERY</code>",
            )
            continue

        genre = parts[1].lower()
        logger.info(f"CREATE {genre.upper()} requested by chat_id={chat_id}")

        await telegram.reply(
            chat_id,
            f"🎬 <b>Creating {genre.upper()} short...</b>\n\nPipeline triggered. You'll get a notification when the video is uploaded.",
        )

        success = await _dispatch_pipeline(genre, github_token, repo)
        if not success:
            await telegram.reply(chat_id, f"❌ Failed to trigger pipeline. Check GitHub Actions.")

    _save_offset(last_update_id + 1)
    logger.info(f"Offset advanced to {last_update_id + 1}")


if __name__ == "__main__":
    asyncio.run(main())
