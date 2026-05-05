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


class SeriesStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"


class StorySeries(Base):
    __tablename__ = "story_series"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(160), nullable=False)
    niche = Column(String(64), nullable=False)
    title_prefix = Column(String(180), nullable=False)
    playlist_name = Column(String(180), nullable=False)
    playlist_id = Column(String(128))
    status = Column(SAEnum(SeriesStatus), default=SeriesStatus.ACTIVE, nullable=False, index=True)
    planned_episodes = Column(Integer, nullable=False)
    started_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
    completed_at = Column(DateTime)


class SeriesEpisode(Base):
    __tablename__ = "series_episodes"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("story_series.id", ondelete="CASCADE"), nullable=False, index=True)
    short_id = Column(Integer, ForeignKey("shorts.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    episode_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
