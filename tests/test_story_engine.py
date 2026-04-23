import pytest
from app.services.story_engine import StoryEngine

ALL_NICHES = ["moral", "mystery", "horror", "motivation", "relationship"]


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
    for niche in ALL_NICHES:
        result = engine.generate(niche)
        assert result["script"], f"Empty script for niche: {niche}"


def test_invalid_niche_raises(engine):
    with pytest.raises(ValueError, match="Unknown niche"):
        engine.generate("invalid_niche")


def test_title_contains_shorts(engine):
    result = engine.generate("moral")
    assert "#shorts" in result["title"].lower()


def test_cta_consistent_in_script_and_dict(engine):
    # The same CTA value must appear in both the script body and the returned dict key
    eng = StoryEngine()
    for _ in range(10):
        result = eng.generate("moral")
        assert result["cta"] in result["script"], (
            f"CTA dict value '{result['cta']}' not found in script: {result['script']}"
        )


@pytest.mark.parametrize("niche", ALL_NICHES)
def test_script_duration_estimate(engine, niche):
    result = engine.generate(niche)
    words = len(result["script"].split())
    duration_seconds = words / 2.5
    assert 15 <= duration_seconds <= 45, (
        f"Script for niche '{niche}' too long/short: {duration_seconds:.1f}s ({words} words)"
    )


def test_no_double_periods_in_script(engine):
    for niche in ALL_NICHES:
        result = engine.generate(niche)
        assert ".." not in result["script"], (
            f"Double period found in {niche} script: {result['script']}"
        )


def test_seo_has_required_keys(engine):
    result = engine.generate("moral")
    seo = result["seo"]
    assert "title" in seo
    assert "description" in seo
    assert "tags" in seo
    assert isinstance(seo["tags"], list)
    assert "#shorts" in seo["tags"]
