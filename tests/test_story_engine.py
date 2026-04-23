import pytest
from app.services.story_engine import StoryEngine

@pytest.fixture
def engine():
    return StoryEngine()

def test_generate_script_returns_dict(engine):
    result = engine.generate("moral")
    assert isinstance(result, dict)
    assert "title" in result
    assert "script" in result
    assert "hook" in result
    assert "pexels_query" in result
    assert "cta" in result

def test_script_starts_with_hook(engine):
    result = engine.generate("moral")
    assert result["script"].startswith(result["hook"])

def test_all_niches_generate(engine):
    for niche in ["moral", "mystery", "horror", "motivation", "relationship"]:
        result = engine.generate(niche)
        assert result["script"], f"Empty script for niche: {niche}"

def test_invalid_niche_raises(engine):
    with pytest.raises(ValueError, match="Unknown niche"):
        engine.generate("invalid_niche")

def test_title_formula(engine):
    result = engine.generate("moral")
    assert "#shorts" in result["title"].lower() or len(result["title"]) > 5

def test_script_duration_estimate(engine):
    result = engine.generate("moral")
    words = len(result["script"].split())
    duration_seconds = words / 2.5
    assert 15 <= duration_seconds <= 45, f"Script too long/short: {duration_seconds:.1f}s"
