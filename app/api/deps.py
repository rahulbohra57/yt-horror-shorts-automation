from app.core.config import settings
from app.core.database import get_engine, get_session_factory

_engine = get_engine(settings.DB_PATH)
_SessionFactory = get_session_factory(_engine)


def get_db():
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()
