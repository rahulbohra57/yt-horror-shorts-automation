import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings
from app.core.database import init_db
from app.api.routes import router
from app.services.scheduler import DailyScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

scheduler = DailyScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core import models  # noqa: F401
    from app.services.telegram_service import TelegramService
    init_db(settings.DB_PATH)
    if settings.SCHEDULER_ENABLED:
        scheduler.start()
    if settings.APP_URL and settings.TELEGRAM_BOT_TOKEN:
        telegram = TelegramService(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
        await telegram.register_webhook(settings.APP_URL)
    yield
    if settings.SCHEDULER_ENABLED:
        scheduler.stop()


app = FastAPI(title="YT Shorts Bot", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def dashboard():
    return FileResponse("app/static/index.html")
