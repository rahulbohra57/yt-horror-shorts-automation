#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.database import get_engine, get_session_factory, init_db
from app.core.models import JobStatus, Short
from app.services.pipeline import Pipeline
from app.services.series_service import SeriesService, is_series_start_day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


ALL_NICHES = [
    "horror", "mystery", "paranormal", "twist_endings",
    "psychological", "supernatural", "slasher", "folk_horror",
]


def _pick_auto_niche(session) -> str:
    """Shuffled-batch rotation: walk through all niches before repeating any."""
    recent = (
        session.query(Short.niche)
        .filter(Short.niche.in_(ALL_NICHES))
        .order_by(Short.created_at.desc(), Short.id.desc())
        .limit(len(ALL_NICHES))
        .all()
    )
    used = [row[0] for row in recent]
    # Niches not yet used in the current batch
    remaining = [n for n in ALL_NICHES if n not in used]
    if not remaining:
        # Full cycle complete — start a fresh shuffled batch
        remaining = ALL_NICHES[:]
    import random as _random
    return _random.choice(remaining)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate and optionally upload one scheduled short.")
    p.add_argument(
        "--niche",
        default="auto",
        choices=["auto"] + ALL_NICHES,
        help="Niche to generate. 'auto' rotates through all genres in shuffled batches.",
    )
    p.add_argument(
        "--upload",
        default="true",
        choices=["true", "false"],
        help="Upload to YouTube when true.",
    )
    p.add_argument(
        "--mode",
        default="story",
        choices=["story", "series"],
        help="Content mode: 'story' for regular shorts, 'series' for continuity episodes.",
    )
    return p.parse_args()


def run_once(session, niche_arg: str, upload: bool, mode: str) -> dict:
    """Runs one scheduled job against the given session. Returns a JSON-serializable result dict."""
    is_series = mode == "series"
    allow_new_series = is_series and is_series_start_day(settings.SCHEDULE_TIMEZONE)

    if is_series:
        series_service = SeriesService()
        if not series_service.has_active_or_startable_series(session, allow_new_series):
            logger.info(
                "Scheduled job skipped: no active series and today is not a series-start day"
            )
            return {"status": "skipped"}

    niche = _pick_auto_niche(session) if niche_arg == "auto" else niche_arg
    short = Short(niche=niche, status=JobStatus.PENDING)
    session.add(short)
    session.commit()
    session.refresh(short)

    logger.info(
        "Starting scheduled pipeline: niche=%s short_id=%s upload=%s mode=%s",
        niche, short.id, upload, mode,
    )
    result = asyncio.run(
        Pipeline().run(
            niche=niche,
            job_id=str(short.id),
            session=session,
            upload=upload,
            series_mode=is_series,
            allow_new_series=allow_new_series,
        )
    )
    return {"short_id": short.id, "niche": niche, "mode": mode, "result": result}


def main() -> int:
    args = parse_args()
    upload = args.upload.lower() == "true"

    init_db(settings.DB_PATH)
    engine = get_engine(settings.DB_PATH)
    SessionFactory = get_session_factory(engine)
    session = SessionFactory()
    try:
        output = run_once(session, args.niche, upload, args.mode)
        print(json.dumps(output, ensure_ascii=True))
        if output.get("status") == "skipped":
            return 0
        if output.get("result", {}).get("status") != "done":
            return 1
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
