from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.database import init_db, get_session_factory
from app.core.models import JobStatus, Short, SeriesStatus, StorySeries
from app.services.series_service import SeriesService, SERIES_EPISODE_RANGE, is_series_start_day


def _make_session(tmp_path):
    engine = init_db(str(tmp_path / "test.db"))
    SessionFactory = get_session_factory(engine)
    return SessionFactory()


def _make_short(session, niche="horror") -> Short:
    short = Short(niche=niche, status=JobStatus.PENDING)
    session.add(short)
    session.commit()
    session.refresh(short)
    return short


def test_episode_range_is_five_or_six():
    assert SERIES_EPISODE_RANGE == (5, 6)


def test_assign_short_returns_none_when_no_active_series_and_new_series_not_allowed(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()
    short = _make_short(session)

    assignment = service.assign_short(session, short, allow_new_series=False)

    assert assignment is None
    assert session.query(StorySeries).count() == 0


def test_assign_short_starts_new_series_when_allowed(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()
    short = _make_short(session)

    assignment = service.assign_short(session, short, allow_new_series=True)

    assert assignment is not None
    assert assignment.episode_number == 1
    series = session.query(StorySeries).filter(StorySeries.id == assignment.series_id).first()
    assert series.status == SeriesStatus.ACTIVE


def test_assign_short_continues_existing_series_even_when_new_series_not_allowed(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()
    first_short = _make_short(session)
    service.assign_short(session, first_short, allow_new_series=True)

    second_short = _make_short(session)
    assignment = service.assign_short(session, second_short, allow_new_series=False)

    assert assignment is not None
    assert assignment.episode_number == 2


def test_rename_series_updates_name_prefix_and_playlist_name(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()
    short = _make_short(session)
    assignment = service.assign_short(session, short, allow_new_series=True)

    service.rename_series(session, assignment.series_id, "The Sleepwood Tapes")

    series = session.query(StorySeries).filter(StorySeries.id == assignment.series_id).first()
    assert series.name == "The Sleepwood Tapes"
    assert series.title_prefix == "The Sleepwood Tapes"
    assert series.playlist_name == "The Sleepwood Tapes Series"


def test_has_active_or_startable_series_true_when_series_active(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()
    short = _make_short(session)
    service.assign_short(session, short, allow_new_series=True)

    assert service.has_active_or_startable_series(session, allow_new_series=False) is True


def test_has_active_or_startable_series_true_when_no_active_series_but_new_allowed(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()

    assert service.has_active_or_startable_series(session, allow_new_series=True) is True


def test_has_active_or_startable_series_false_when_no_active_series_and_new_not_allowed(tmp_path):
    session = _make_session(tmp_path)
    service = SeriesService()

    assert service.has_active_or_startable_series(session, allow_new_series=False) is False


def test_is_series_start_day_true_on_monday():
    monday = datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert is_series_start_day("Asia/Kolkata", now=monday) is True


def test_is_series_start_day_false_on_tuesday():
    tuesday = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert is_series_start_day("Asia/Kolkata", now=tuesday) is False
