from unittest.mock import MagicMock, patch

from app.core.database import init_db, get_session_factory
from app.core.models import JobStatus, Short


def _make_session(tmp_path):
    engine = init_db(str(tmp_path / "test.db"))
    SessionFactory = get_session_factory(engine)
    return SessionFactory()


async def _async_done_coro():
    return {"status": "done", "youtube_url": "https://youtube.com/shorts/abc"}


def _async_done():
    return _async_done_coro()


def test_run_once_skips_when_series_mode_has_nothing_postable(tmp_path):
    from scripts.run_scheduled_job import run_once

    session = _make_session(tmp_path)

    with patch("scripts.run_scheduled_job.is_series_start_day", return_value=False):
        output = run_once(session, niche_arg="auto", upload=True, mode="series")

    assert output == {"status": "skipped"}
    assert session.query(Short).count() == 0


def test_run_once_runs_series_mode_and_passes_allow_new_series(tmp_path):
    from scripts.run_scheduled_job import run_once

    session = _make_session(tmp_path)

    with patch("scripts.run_scheduled_job.is_series_start_day", return_value=True), \
         patch("scripts.run_scheduled_job.Pipeline") as MockPipeline:
        MockPipeline.return_value.run = MagicMock(return_value=_async_done())

        output = run_once(session, niche_arg="horror", upload=True, mode="series")

        _, kwargs = MockPipeline.return_value.run.call_args
        assert kwargs["series_mode"] is True
        assert kwargs["allow_new_series"] is True

    assert output["result"]["status"] == "done"
    assert session.query(Short).count() == 1


def test_run_once_story_mode_never_series_and_always_runs(tmp_path):
    from scripts.run_scheduled_job import run_once

    session = _make_session(tmp_path)

    with patch("scripts.run_scheduled_job.is_series_start_day", return_value=True), \
         patch("scripts.run_scheduled_job.Pipeline") as MockPipeline:
        MockPipeline.return_value.run = MagicMock(return_value=_async_done())

        output = run_once(session, niche_arg="horror", upload=True, mode="story")

        _, kwargs = MockPipeline.return_value.run.call_args
        assert kwargs["series_mode"] is False
        assert kwargs["allow_new_series"] is False

    assert output["result"]["status"] == "done"
