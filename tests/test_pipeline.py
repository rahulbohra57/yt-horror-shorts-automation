import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_pipeline_imports():
    from app.services.pipeline import Pipeline
    assert Pipeline is not None


def test_pipeline_update_status_on_failure():
    """Pipeline must set FAILED status and not raise when a service fails."""
    from app.services.pipeline import Pipeline
    from app.core.models import JobStatus

    with patch("app.services.pipeline.settings.GEMINI_API_KEY", "test-key"), \
         patch("app.services.pipeline.GeminiStoryEngine") as MockStory, \
         patch("app.services.pipeline.PexelsService"), \
         patch("app.services.pipeline.TTSService"), \
         patch("app.services.pipeline.RenderService"), \
         patch("app.services.pipeline.YouTubeService"):

        MockStory.return_value.generate.side_effect = RuntimeError("story gen failed")
        pipeline = Pipeline()

        mock_short = MagicMock()
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_short

        import asyncio
        result = asyncio.run(pipeline.run("moral", "1", mock_session, upload=False))

    assert result["status"] == "failed"
    assert "story gen failed" in result["error"]


def test_compute_is_final_episode_true_when_no_assignment():
    from app.services.pipeline import Pipeline
    assert Pipeline._compute_is_final_episode(None) is True


def test_compute_is_final_episode_true_on_last_episode():
    from app.services.pipeline import Pipeline
    from app.services.series_service import SeriesAssignment

    assignment = SeriesAssignment(
        series_id=1, series_name="X", title_prefix="X", playlist_name="X Series",
        episode_number=5, planned_episodes=5,
    )
    assert Pipeline._compute_is_final_episode(assignment) is True


def test_compute_is_final_episode_false_mid_series():
    from app.services.pipeline import Pipeline
    from app.services.series_service import SeriesAssignment

    assignment = SeriesAssignment(
        series_id=1, series_name="X", title_prefix="X", playlist_name="X Series",
        episode_number=2, planned_episodes=5,
    )
    assert Pipeline._compute_is_final_episode(assignment) is False


def test_load_recent_context_is_cross_niche(tmp_path):
    from app.core.database import init_db, get_session_factory
    from app.core.models import Short, JobStatus
    from app.services.pipeline import Pipeline

    engine = init_db(str(tmp_path / "test.db"))
    SessionFactory = get_session_factory(engine)
    session = SessionFactory()

    other_niche_short = Short(
        niche="mystery", status=JobStatus.DONE,
        script="A mystery script.", title="Mystery Title", hook="A mystery hook.",
    )
    session.add(other_niche_short)
    session.commit()
    session.refresh(other_niche_short)

    current_short = Short(niche="horror", status=JobStatus.PENDING)
    session.add(current_short)
    session.commit()
    session.refresh(current_short)

    scripts, titles, hooks = Pipeline._load_recent_context(session, str(current_short.id))

    assert "A mystery script." in scripts
    assert "Mystery Title" in titles
    assert "A mystery hook." in hooks


def test_maybe_rename_series_updates_assignment_on_episode_one():
    from app.services.pipeline import Pipeline
    from app.services.series_service import SeriesAssignment

    with patch("app.services.pipeline.settings.GEMINI_API_KEY", "test-key"), \
         patch("app.services.pipeline.GeminiStoryEngine"), \
         patch("app.services.pipeline.PexelsService"), \
         patch("app.services.pipeline.TTSService"), \
         patch("app.services.pipeline.RenderService"), \
         patch("app.services.pipeline.YouTubeService"):
        pipeline = Pipeline()

    pipeline.story = MagicMock()
    pipeline.story.generate_series_title.return_value = "The Sleepwood Tapes"
    pipeline.series = MagicMock()

    assignment = SeriesAssignment(
        series_id=7, series_name="placeholder", title_prefix="placeholder",
        playlist_name="placeholder Series", episode_number=1, planned_episodes=5,
    )
    story = {"hook": "A hook.", "script": "A script."}
    session = MagicMock()

    result = pipeline._maybe_rename_series(session, "1", assignment, "horror", story)

    pipeline.series.rename_series.assert_called_once_with(session, 7, "The Sleepwood Tapes")
    assert result.series_name == "The Sleepwood Tapes"
    assert result.title_prefix == "The Sleepwood Tapes"
    assert result.playlist_name == "The Sleepwood Tapes Series"


def test_maybe_rename_series_noop_after_episode_one():
    from app.services.pipeline import Pipeline
    from app.services.series_service import SeriesAssignment

    with patch("app.services.pipeline.settings.GEMINI_API_KEY", "test-key"), \
         patch("app.services.pipeline.GeminiStoryEngine"), \
         patch("app.services.pipeline.PexelsService"), \
         patch("app.services.pipeline.TTSService"), \
         patch("app.services.pipeline.RenderService"), \
         patch("app.services.pipeline.YouTubeService"):
        pipeline = Pipeline()

    pipeline.story = MagicMock()
    pipeline.series = MagicMock()
    assignment = SeriesAssignment(
        series_id=7, series_name="Real Name", title_prefix="Real Name",
        playlist_name="Real Name Series", episode_number=2, planned_episodes=5,
    )

    result = pipeline._maybe_rename_series(MagicMock(), "1", assignment, "horror", {"hook": "h", "script": "s"})

    pipeline.series.rename_series.assert_not_called()
    assert result is assignment


def test_maybe_rename_series_falls_back_on_gemini_failure():
    from app.services.pipeline import Pipeline
    from app.services.series_service import SeriesAssignment

    with patch("app.services.pipeline.settings.GEMINI_API_KEY", "test-key"), \
         patch("app.services.pipeline.GeminiStoryEngine"), \
         patch("app.services.pipeline.PexelsService"), \
         patch("app.services.pipeline.TTSService"), \
         patch("app.services.pipeline.RenderService"), \
         patch("app.services.pipeline.YouTubeService"):
        pipeline = Pipeline()

    pipeline.story = MagicMock()
    pipeline.story.generate_series_title.side_effect = ValueError("bad title")
    pipeline.series = MagicMock()
    assignment = SeriesAssignment(
        series_id=7, series_name="placeholder", title_prefix="placeholder",
        playlist_name="placeholder Series", episode_number=1, planned_episodes=5,
    )

    result = pipeline._maybe_rename_series(MagicMock(), "1", assignment, "horror", {"hook": "h", "script": "s"})

    pipeline.series.rename_series.assert_not_called()
    assert result is assignment


def test_apply_series_title_prefix_uses_series_name_and_episode_only():
    from app.services.pipeline import Pipeline

    story = {
        "title": "The Rose In My Empty Bed #Shorts",
        "seo": {
            "title": "The Rose In My Empty Bed #Shorts",
            "description": "The Rose In My Empty Bed #Shorts\n\nrest of description",
            "tags": ["shorts", "horror"],
        },
    }

    result = Pipeline._apply_series_title_prefix(story, "Shadow Protocol", 2)

    assert result["title"] == "Shadow Protocol | Ep 2 #Shorts"
    assert result["seo"]["title"] == "Shadow Protocol | Ep 2 #Shorts"
    assert result["seo"]["description"].startswith("Shadow Protocol | Ep 2 #Shorts")
    assert result["seo"]["description"].endswith("rest of description")


def test_run_forwards_allow_new_series_to_series_assignment():
    from app.services.pipeline import Pipeline

    with patch("app.services.pipeline.settings.GEMINI_API_KEY", "test-key"), \
         patch("app.services.pipeline.GeminiStoryEngine") as MockStory, \
         patch("app.services.pipeline.PexelsService"), \
         patch("app.services.pipeline.TTSService"), \
         patch("app.services.pipeline.RenderService"), \
         patch("app.services.pipeline.YouTubeService"):

        MockStory.return_value.generate.side_effect = RuntimeError("stop after assignment check")
        pipeline = Pipeline()
        pipeline.series = MagicMock()
        pipeline.series.assign_short.return_value = None

        mock_short = MagicMock()
        mock_short.niche = "horror"
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_short
        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        import asyncio
        asyncio.run(pipeline.run("horror", "1", mock_session, upload=False, series_mode=True, allow_new_series=True))

    pipeline.series.assign_short.assert_called_once_with(mock_session, mock_short, allow_new_series=True)
