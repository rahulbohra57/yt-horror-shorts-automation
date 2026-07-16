from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


def test_series_slot_uses_configured_time_when_present():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.settings.SCHEDULE_TIMES", "00:10,06:10,12:10,18:10"), \
         patch("app.services.scheduler.settings.SERIES_SLOT_TIME", "12:10"):
        scheduler = DailyScheduler()
        assert scheduler._series_slot() == (12, 10)


def test_series_slot_falls_back_to_earliest_time_when_configured_time_absent():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.settings.SCHEDULE_TIMES", "01:00,07:00"), \
         patch("app.services.scheduler.settings.SERIES_SLOT_TIME", "12:10"):
        scheduler = DailyScheduler()
        assert scheduler._series_slot() == (1, 0)


def test_is_series_start_day_true_on_monday():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.settings.SCHEDULE_TIMEZONE", "Asia/Kolkata"):
        scheduler = DailyScheduler()
        monday = datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # a Monday
        assert scheduler._is_series_start_day(now=monday) is True


def test_is_series_start_day_false_on_tuesday():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.settings.SCHEDULE_TIMEZONE", "Asia/Kolkata"):
        scheduler = DailyScheduler()
        tuesday = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert scheduler._is_series_start_day(now=tuesday) is False


async def _async_none_coro():
    return None


def _async_none():
    return _async_none_coro()


def test_run_daily_job_passes_series_mode_and_allow_new_series_on_series_slot():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.get_engine"), \
         patch("app.services.scheduler.get_session_factory") as mock_factory, \
         patch("app.services.scheduler.Pipeline") as MockPipeline, \
         patch("app.services.scheduler.settings.SCHEDULE_UPLOAD", True):

        mock_session = MagicMock()
        mock_factory.return_value.return_value = mock_session
        MockPipeline.return_value.run = MagicMock(return_value=_async_none())

        scheduler = DailyScheduler()
        scheduler._pick_niche = MagicMock(return_value="horror")
        scheduler._is_series_start_day = MagicMock(return_value=True)
        scheduler.series.has_active_or_startable_series = MagicMock(return_value=True)

        scheduler._run_daily_job(is_series_slot=True)

        _, kwargs = MockPipeline.return_value.run.call_args
        assert kwargs["series_mode"] is True
        assert kwargs["allow_new_series"] is True


def test_run_daily_job_standalone_slot_never_allows_new_series():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.get_engine"), \
         patch("app.services.scheduler.get_session_factory") as mock_factory, \
         patch("app.services.scheduler.Pipeline") as MockPipeline, \
         patch("app.services.scheduler.settings.SCHEDULE_UPLOAD", True):

        mock_session = MagicMock()
        mock_factory.return_value.return_value = mock_session
        MockPipeline.return_value.run = MagicMock(return_value=_async_none())

        scheduler = DailyScheduler()
        scheduler._pick_niche = MagicMock(return_value="mystery")
        scheduler._is_series_start_day = MagicMock(return_value=True)

        scheduler._run_daily_job(is_series_slot=False)

        _, kwargs = MockPipeline.return_value.run.call_args
        assert kwargs["series_mode"] is False
        assert kwargs["allow_new_series"] is False


def test_run_daily_job_skips_when_series_slot_has_nothing_postable():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.get_engine"), \
         patch("app.services.scheduler.get_session_factory") as mock_factory, \
         patch("app.services.scheduler.Pipeline") as MockPipeline, \
         patch("app.services.scheduler.settings.SCHEDULE_UPLOAD", True):

        mock_session = MagicMock()
        mock_factory.return_value.return_value = mock_session
        MockPipeline.return_value.run = MagicMock(return_value=_async_none())

        scheduler = DailyScheduler()
        scheduler._pick_niche = MagicMock(return_value="horror")
        scheduler._is_series_start_day = MagicMock(return_value=False)
        scheduler.series.has_active_or_startable_series = MagicMock(return_value=False)

        scheduler._run_daily_job(is_series_slot=True)

        MockPipeline.return_value.run.assert_not_called()
        mock_session.add.assert_not_called()


def test_run_daily_job_runs_when_series_slot_has_active_series():
    from app.services.scheduler import DailyScheduler

    with patch("app.services.scheduler.get_engine"), \
         patch("app.services.scheduler.get_session_factory") as mock_factory, \
         patch("app.services.scheduler.Pipeline") as MockPipeline, \
         patch("app.services.scheduler.settings.SCHEDULE_UPLOAD", True):

        mock_session = MagicMock()
        mock_factory.return_value.return_value = mock_session
        MockPipeline.return_value.run = MagicMock(return_value=_async_none())

        scheduler = DailyScheduler()
        scheduler._pick_niche = MagicMock(return_value="horror")
        scheduler._is_series_start_day = MagicMock(return_value=False)
        scheduler.series.has_active_or_startable_series = MagicMock(return_value=True)

        scheduler._run_daily_job(is_series_slot=True)

        MockPipeline.return_value.run.assert_called_once()
