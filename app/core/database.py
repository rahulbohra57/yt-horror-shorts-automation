import logging
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_ADDED_COLUMNS = [
    ("shorts", "cta", "TEXT"),
    ("shorts", "premise", "TEXT"),
    ("story_series", "bible", "TEXT"),
]


def get_engine(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    return engine


def init_db(db_path: str):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations(engine)
    logger.info(f"Database initialized at {db_path}")
    return engine


def _apply_lightweight_migrations(engine):
    """create_all only creates missing tables, not missing columns on tables
    that already exist in a deployed DB file. Patch those in here instead of
    pulling in a full migration framework for a single-file SQLite project."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for table, column, column_type in _ADDED_COLUMNS:
        if table not in tables:
            continue
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
            logger.info(f"Migrated {table} table: added {column} column")


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
