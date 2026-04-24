import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.models import JobStatus, Short

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_NICHES = ["horror", "mystery"]


class GenerateRequest(BaseModel):
    niche: str
    upload: bool = True


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/niches")
def list_niches():
    return {"niches": VALID_NICHES}


@router.get("/api/shorts")
def list_shorts(db: Session = Depends(get_db)):
    shorts = db.query(Short).order_by(Short.created_at.desc()).limit(50).all()
    return [
        {
            "id": s.id,
            "niche": s.niche,
            "title": s.title,
            "status": s.status,
            "youtube_url": s.youtube_url,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "error_message": s.error_message,
        }
        for s in shorts
    ]


@router.get("/api/shorts/{short_id}")
def get_short(short_id: int, db: Session = Depends(get_db)):
    short = db.query(Short).filter(Short.id == short_id).first()
    if not short:
        raise HTTPException(status_code=404, detail="Short not found")
    return {
        "id": short.id,
        "niche": short.niche,
        "title": short.title,
        "script": short.script,
        "status": short.status,
        "youtube_url": short.youtube_url,
        "error_message": short.error_message,
    }


@router.post("/api/generate")
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if req.niche not in VALID_NICHES:
        raise HTTPException(status_code=422, detail=f"Invalid niche. Choose from: {VALID_NICHES}")

    from app.core import models  # ensure models imported for init_db
    short = Short(niche=req.niche, status=JobStatus.PENDING)
    db.add(short)
    db.commit()
    db.refresh(short)

    background_tasks.add_task(_run_pipeline, req.niche, str(short.id), req.upload)
    return {"job_id": short.id, "status": "queued", "niche": req.niche}


async def _run_pipeline(niche: str, job_id: str, upload: bool):
    from app.core.config import settings
    from app.core.database import get_engine, get_session_factory
    from app.services.pipeline import Pipeline

    engine = get_engine(settings.DB_PATH)
    SessionFactory = get_session_factory(engine)
    session = SessionFactory()
    try:
        pipeline = Pipeline()
        await pipeline.run(niche=niche, job_id=job_id, session=session, upload=upload)
    finally:
        session.close()
