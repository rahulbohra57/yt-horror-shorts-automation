"""Local pipeline runner — used for testing. Delete after debugging."""
import asyncio
import logging
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings
from app.core.database import get_engine, get_session_factory
from app.core.models import Base, Short, JobStatus
from app.services.pipeline import Pipeline


async def main(niche: str = "horror", upload: bool = True):
    print(f"\n=== Running pipeline: niche={niche}, upload={upload} ===\n")

    engine = get_engine(settings.DB_PATH)
    Base.metadata.create_all(engine)
    SessionFactory = get_session_factory(engine)
    session = SessionFactory()

    try:
        short = Short(niche=niche, status=JobStatus.PENDING)
        session.add(short)
        session.commit()
        session.refresh(short)
        job_id = str(short.id)
        print(f"Created job ID: {job_id}")

        pipeline = Pipeline()
        result = await pipeline.run(niche=niche, job_id=job_id, session=session, upload=upload)
        print(f"\n=== Result ===\n{result}\n")
        return result
    finally:
        session.close()


if __name__ == "__main__":
    niche = sys.argv[1] if len(sys.argv) > 1 else "horror"
    upload = sys.argv[2].lower() != "false" if len(sys.argv) > 2 else True
    asyncio.run(main(niche=niche, upload=upload))
