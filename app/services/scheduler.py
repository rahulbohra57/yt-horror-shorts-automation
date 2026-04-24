import asyncio
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.core.database import get_engine, get_session_factory
from app.core.models import Short, JobStatus
from app.services.pipeline import Pipeline

logger = logging.getLogger(__name__)

DEFAULT_NICHES = ["horror", "mystery"]


class DailyScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=settings.SCHEDULE_TIMEZONE)
        self._run_lock = threading.Lock()

    def _parse_schedule_times(self) -> list[tuple[int, int]]:
        times = []
        raw = (settings.SCHEDULE_TIMES or "").split(",")
        for item in raw:
            item = item.strip()
            if not item:
                continue
            try:
                hour_str, minute_str = item.split(":")
                hour = int(hour_str)
                minute = int(minute_str)
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    times.append((hour, minute))
            except Exception:
                logger.warning(f"Invalid schedule time '{item}' ignored. Expected HH:MM.")
        if not times:
            return [(0, 10), (6, 10), (12, 10), (18, 10)]
        return sorted(set(times))

    def _niches(self) -> list[str]:
        raw = [x.strip().lower() for x in (settings.SCHEDULE_NICHES or "").split(",") if x.strip()]
        niches = [x for x in raw if x in {"horror", "mystery"}]
        return niches or DEFAULT_NICHES

    def start(self):
        for hour, minute in self._parse_schedule_times():
            job_id = f"scheduled_short_{hour:02d}{minute:02d}"
            self.scheduler.add_job(
                self._run_daily_job,
                trigger=CronTrigger(hour=hour, minute=minute),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=settings.SCHEDULE_MISFIRE_GRACE_SECONDS,
            )
        self.scheduler.start()
        readable = ", ".join(f"{h:02d}:{m:02d}" for h, m in self._parse_schedule_times())
        logger.info(
            "Scheduler started: times=%s timezone=%s niches=%s upload=%s",
            readable,
            settings.SCHEDULE_TIMEZONE,
            self._niches(),
            settings.SCHEDULE_UPLOAD,
        )

    def stop(self):
        self.scheduler.shutdown(wait=False)

    def _pick_niche(self, session) -> str:
        niches = self._niches()
        last = (
            session.query(Short)
            .filter(Short.niche.in_(niches))
            .order_by(Short.created_at.desc(), Short.id.desc())
            .first()
        )
        if not last:
            return niches[0]
        if len(niches) == 1:
            return niches[0]
        try:
            idx = niches.index(last.niche)
            return niches[(idx + 1) % len(niches)]
        except ValueError:
            return niches[0]

    def _run_daily_job(self):
        if not self._run_lock.acquire(blocking=False):
            logger.warning("Scheduled job skipped: previous run still in progress")
            return

        engine = get_engine(settings.DB_PATH)
        SessionFactory = get_session_factory(engine)
        session = SessionFactory()
        try:
            niche = self._pick_niche(session)
            logger.info(f"Scheduled job triggered: niche={niche}")
            short = Short(niche=niche, status=JobStatus.PENDING)
            session.add(short)
            session.commit()
            session.refresh(short)
            pipeline = Pipeline()
            asyncio.run(
                pipeline.run(
                    niche=niche,
                    job_id=str(short.id),
                    session=session,
                    upload=settings.SCHEDULE_UPLOAD,
                )
            )
        except Exception as e:
            logger.error(f"Scheduled job failed: {e}", exc_info=True)
        finally:
            session.close()
            self._run_lock.release()
