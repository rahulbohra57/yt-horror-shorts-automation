import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_pipeline_imports():
    from app.services.pipeline import Pipeline
    assert Pipeline is not None


def test_pipeline_update_status_on_failure():
    """Pipeline must set FAILED status and not raise when a service fails."""
    from app.services.pipeline import Pipeline
    from app.core.models import JobStatus

    with patch("app.services.pipeline.StoryEngine") as MockStory, \
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
