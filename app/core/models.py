import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SAEnum, ForeignKey
from app.core.database import Base


def _utcnow():
    # SQLite stores naive datetimes as strings; we strip tzinfo intentionally
    # so all DateTime columns in this schema store UTC-naive values.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    RENDERING = "rendering"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"


class Short(Base):
    __tablename__ = "shorts"

    id = Column(Integer, primary_key=True, index=True)
    niche = Column(String(64), nullable=False)
    title = Column(String(256))
    script = Column(Text)
    hook = Column(String(512))
    pexels_query = Column(String(256))
    video_path = Column(String(512))
    youtube_url = Column(String(512))
    status = Column(SAEnum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<Short id={self.id} niche={self.niche} status={self.status}>"


class Analytics(Base):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True, index=True)
    short_id = Column(Integer, ForeignKey("shorts.id", ondelete="CASCADE"), nullable=False)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    fetched_at = Column(DateTime, default=_utcnow)
