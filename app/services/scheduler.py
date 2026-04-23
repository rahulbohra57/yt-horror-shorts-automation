import asyncio
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.core.database import get_engine, get_session_factory, init_db
from app.core.models import Short, JobStatus
from app.services.pipeline import Pipeline

logger = logging.getLogger(__name__)

NICHE_ROTATION = ["moral", "mystery", "horror", "motivation", "relationship"]


class DailyScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self._niche_index = 0

    def start(self):
        self.scheduler.add_job(
            self._run_daily_job,
            trigger=CronTrigger(hour=settings.SCHEDULE_HOUR, minute=settings.SCHEDULE_MINUTE),
            id="daily_short",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info(f"Scheduler started: daily at {settings.SCHEDULE_HOUR:02}:{settings.SCHEDULE_MINUTE:02}")

    def stop(self):
        self.scheduler.shutdown(wait=False)

    def _run_daily_job(self):
        niche = NICHE_ROTATION[self._niche_index % len(NICHE_ROTATION)]
        self._niche_index += 1
        logger.info(f"Scheduled job triggered: niche={niche}")

        engine = get_engine(settings.DB_PATH)
        SessionFactory = get_session_factory(engine)
        session = SessionFactory()
        try:
            short = Short(niche=niche, status=JobStatus.PENDING)
            session.add(short)
            session.commit()
            session.refresh(short)
            pipeline = Pipeline()
            asyncio.run(pipeline.run(niche=niche, job_id=str(short.id), session=session, upload=True))
        finally:
            session.close()
