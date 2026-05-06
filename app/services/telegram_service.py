import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_SET_WEBHOOK = "https://api.telegram.org/bot{token}/setWebhook"


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

    async def notify_gemini_failed(self, niche: str, error: str) -> None:
        short_error = error[:400] if len(error) > 400 else error
        await self.send(
            f"🤖 <b>Gemini story generation failed</b>\n"
            f"Niche: <code>{niche}</code>\n"
            f"Error: <code>{short_error}</code>\n\n"
            f"⚠️ Generation could not complete after retries. "
            f"This can be due to model/API issues or content validation constraints. "
            f"Pipeline has been stopped."
        )

    async def reply(self, chat_id: int | str, text: str) -> None:
        """Send a message to a specific chat (used to reply to webhook messages)."""
        if not self._token:
            return
        url = TELEGRAM_API.format(token=self._token)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Telegram reply failed: {e}")

    async def register_webhook(self, app_url: str) -> None:
        """Register the Telegram webhook with our FastAPI endpoint URL."""
        if not self._token:
            logger.debug("Telegram not configured, skipping webhook registration")
            return
        webhook_url = f"{app_url.rstrip('/')}/telegram/webhook"
        url = TELEGRAM_SET_WEBHOOK.format(token=self._token)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"url": webhook_url, "allowed_updates": ["message"]})
                data = resp.json()
            if data.get("ok"):
                logger.info(f"Telegram webhook registered: {webhook_url}")
            else:
                logger.warning(f"Telegram webhook registration failed: {data}")
        except Exception as e:
            logger.warning(f"Telegram webhook registration error: {e}")
