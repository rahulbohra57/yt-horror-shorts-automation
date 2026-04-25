import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramService:
    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

    async def send(self, text: str) -> None:
        if not self._enabled:
            logger.debug("Telegram not configured, skipping notification")
            return
        url = TELEGRAM_API.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")

    async def notify_started(self, niche: str, job_id: str) -> None:
        await self.send(
            f"🎬 <b>Video creation started</b>\n"
            f"Niche: <code>{niche}</code>\n"
            f"Job ID: <code>{job_id}</code>"
        )

    async def notify_uploaded(self, title: str, youtube_url: str, niche: str) -> None:
        await self.send(
            f"✅ <b>Video uploaded!</b>\n"
            f"🎞 {title}\n"
            f"Niche: <code>{niche}</code>\n"
            f"🔗 <a href=\"{youtube_url}\">{youtube_url}</a>"
        )

    async def notify_failed(self, job_id: str, niche: str, error: str) -> None:
        short_error = error[:400] if len(error) > 400 else error
        await self.send(
            f"❌ <b>Pipeline failed</b>\n"
            f"Niche: <code>{niche}</code>\n"
            f"Job ID: <code>{job_id}</code>\n"
            f"Error: <code>{short_error}</code>"
        )
