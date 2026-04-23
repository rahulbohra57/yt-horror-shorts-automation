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
    # Import all models before init_db so create_all picks them up
    from app.core import models  # noqa: F401
    init_db(settings.DB_PATH)
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="YT Shorts Bot", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def dashboard():
    return FileResponse("app/static/index.html")
