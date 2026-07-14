import asyncio
import logging
import random
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.core.database import get_engine, get_session_factory
from app.core.models import Short, JobStatus
from app.services.pipeline import Pipeline

logger = logging.getLogger(__name__)

DEFAULT_NICHES = [
    "horror",
    "mystery",
    "paranormal",
    "twist_endings",
    "psychological",
    "supernatural",
    "slasher",
    "folk_horror",
]


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
        valid = set(DEFAULT_NICHES)
        raw = [x.strip().lower() for x in (settings.SCHEDULE_NICHES or "").split(",") if x.strip()]
        niches = [x for x in raw if x in valid]
        return niches or DEFAULT_NICHES

    def _series_slot(self) -> tuple[int, int]:
        times = self._parse_schedule_times()
        raw = (settings.SERIES_SLOT_TIME or "").strip()
        try:
            hour_str, minute_str = raw.split(":")
            candidate = (int(hour_str), int(minute_str))
            if candidate in times:
                return candidate
        except Exception:
            pass
        return times[0]

    def _is_series_start_day(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(ZoneInfo(settings.SCHEDULE_TIMEZONE))
        return current.weekday() == 0

    def start(self):
        series_slot = self._series_slot()
        for hour, minute in self._parse_schedule_times():
            job_id = f"scheduled_short_{hour:02d}{minute:02d}"
            is_series_slot = (hour, minute) == series_slot
            self.scheduler.add_job(
                self._run_daily_job,
                args=[is_series_slot],
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
            "Scheduler started: times=%s timezone=%s niches=%s upload=%s series_slot=%02d:%02d",
            readable,
            settings.SCHEDULE_TIMEZONE,
            self._niches(),
            settings.SCHEDULE_UPLOAD,
            series_slot[0], series_slot[1],
        )

    def stop(self):
        self.scheduler.shutdown(wait=False)

    def _pick_niche(self, session) -> str:
        """
        Shuffled-batch selection: cycle through all niches in a random order,
        then reshuffle for the next round. Guarantees every genre appears once
        per batch with no predictable pattern.
        """
        niches = self._niches()
        if len(niches) == 1:
            return niches[0]

        # Look back 2 full batches to reliably detect the batch boundary.
        recent_rows = (
            session.query(Short.niche)
            .filter(Short.niche.in_(niches))
            .order_by(Short.created_at.desc(), Short.id.desc())
            .limit(len(niches) * 2)
            .all()
        )
        recent = [row[0] for row in recent_rows]

        # Walk backwards from the most recent post. The first repeated niche
        # marks the end of the previous batch — everything before it is the
        # current batch's already-used genres.
        used = set()
        for n in recent:
            if n in used:
                break
            used.add(n)

        remaining = [n for n in niches if n not in used]
        if not remaining:
            # Current batch complete — start a fresh shuffled batch.
            remaining = list(niches)

        chosen = random.choice(remaining)
        logger.info(
            "Niche picker: used_this_batch=%s remaining=%s chosen=%s",
            sorted(used), remaining, chosen,
        )
        return chosen

    def _run_daily_job(self, is_series_slot: bool = False):
        if not self._run_lock.acquire(blocking=False):
            logger.warning("Scheduled job skipped: previous run still in progress")
            return

        engine = get_engine(settings.DB_PATH)
        SessionFactory = get_session_factory(engine)
        session = SessionFactory()
        try:
            niche = self._pick_niche(session)
            allow_new_series = is_series_slot and self._is_series_start_day()
            logger.info(
                "Scheduled job triggered: niche=%s series_slot=%s allow_new_series=%s",
                niche, is_series_slot, allow_new_series,
            )
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
                    series_mode=is_series_slot,
                    allow_new_series=allow_new_series,
                )
            )
        except Exception as e:
            logger.error(f"Scheduled job failed: {e}", exc_info=True)
        finally:
            session.close()
            self._run_lock.release()
