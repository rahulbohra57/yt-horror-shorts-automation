import os
import pytest
from app.core.config import settings


def test_settings_load():
    assert settings.DB_PATH is not None
    assert settings.MEDIA_CACHE_DIR is not None


def test_db_path_has_default():
    assert "shorts" in settings.DB_PATH


def test_db_init_creates_tables(tmp_path):
    from app.core.database import init_db, get_session_factory
    from app.core.models import Short, JobStatus

    db_path = str(tmp_path / "test.db")
    engine = init_db(db_path)
    SessionFactory = get_session_factory(engine)
    session = SessionFactory()

    short = Short(niche="moral", status=JobStatus.PENDING)
    session.add(short)
    session.commit()

    fetched = session.query(Short).filter_by(niche="moral").first()
    assert fetched is not None
    assert fetched.status == JobStatus.PENDING
    session.close()
