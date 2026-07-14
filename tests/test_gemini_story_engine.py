import json

from app.services.gemini_story_engine import GeminiStoryEngine
from app.services.pipeline import Pipeline


class DummyGeminiResponse:
    text = json.dumps({
        "hook": "The old phone rang from inside the wall.",
        "title": "The Phone Inside The Wall",
        "script": "The old phone rang from inside the wall. Mia pulled away the plaster and found it sealed in concrete. The screen showed one message from her own number. It said, stop digging. She called the number anyway. Somewhere behind her, a second phone began to ring.",
    })


class DummyGeminiModel:
    def generate_content(self, *args, **kwargs):
        return DummyGeminiResponse()


def test_gemini_uses_niche_cta_pool():
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {
        "horror": {
            "ctas": ["Follow for a new horror story every night."],
        }
    }
    engine._model = DummyGeminiModel()

    hook, script, cta, title_seed, scene_queries = engine._call_gemini("horror", [])

    assert hook == "The old phone rang from inside the wall."
    assert title_seed == "The Phone Inside The Wall"
    assert cta == "Follow for a new horror story every night."
    assert script.endswith(cta)


def test_gemini_falls_back_to_default_cta_pool_when_niche_has_none():
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {"unknown": {"ctas": []}}

    assert engine._cta_pool_for("unknown") == GeminiStoryEngine._CTA_POOL


def test_pipeline_appends_cta_before_tts_if_metadata_and_script_drift():
    story = {
        "script": "The story ends on a creepy line.",
        "cta": "Subscribe before midnight.",
    }

    fixed = Pipeline._ensure_cta_in_script(story)

    assert fixed["script"] == "The story ends on a creepy line. Subscribe before midnight."


def test_title_is_complete_and_has_no_broken_genre_hashtag():
    engine = object.__new__(GeminiStoryEngine)

    title = engine._generate_title(
        "psychological",
        "The antique locket I found in the attic had a perfect tiny heartbeat inside it",
        "The Attic Locket Had A Heartbeat",
    )

    assert title == "The Attic Locket Had A Heartbeat #Shorts"
    assert "#Psychological Horror" not in title
    assert len(title) <= 100


def test_script_is_forced_to_start_with_hook():
    engine = object.__new__(GeminiStoryEngine)

    script = engine._ensure_hook_starts_script(
        "Back home, the mirror had already learned my name.",
        "I found my own obituary under the bed.",
    )

    assert script.startswith("I found my own obituary under the bed.")


class DummySeriesGeminiResponse:
    text = json.dumps({
        "hook": "You hear your own voice through the baby monitor.",
        "title": "The Voice In The Monitor",
        "script": "You hear your own voice through the baby monitor. Sarah checked the nursery twice, but it was empty. The voice kept repeating the same six words. She pressed record to prove she was imagining it. When she played it back, a second voice answered hers. It was already inside the house.",
    })


class DummySeriesGeminiModel:
    def generate_content(self, *args, **kwargs):
        return DummySeriesGeminiResponse()


def test_non_final_series_episode_gets_cliffhanger_ending_and_cta():
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {"horror": {}}
    engine._model = DummySeriesGeminiModel()

    hook, script, cta, title_seed, scene_queries = engine._call_gemini(
        "horror",
        [],
        series_context="EP1 TITLE: The Voice\nEP1 SUMMARY: A voice answered back.",
        series_episode_number=2,
        series_name="The Monitor Files",
        is_final_episode=False,
    )

    from app.services.gemini_story_engine import CTA_BUCKETS
    assert cta in CTA_BUCKETS["cliffhanger"]


def test_final_series_episode_keeps_normal_cta_pool():
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {"horror": {"ctas": ["Follow for the next nightmare."]}}
    engine._model = DummySeriesGeminiModel()

    hook, script, cta, title_seed, scene_queries = engine._call_gemini(
        "horror",
        [],
        series_context="EP1 TITLE: The Voice\nEP1 SUMMARY: A voice answered back.",
        series_episode_number=3,
        series_name="The Monitor Files",
        is_final_episode=True,
    )

    assert cta == "Follow for the next nightmare."


def test_standalone_short_defaults_to_final_episode_behavior():
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {"horror": {"ctas": ["Follow for the next nightmare."]}}
    engine._model = DummySeriesGeminiModel()

    hook, script, cta, title_seed, scene_queries = engine._call_gemini("horror", [])

    assert cta == "Follow for the next nightmare."


class DummyTitleGeminiResponse:
    text = "The Sleepwood Tapes"


class DummyTitleGeminiModel:
    def generate_content(self, *args, **kwargs):
        return DummyTitleGeminiResponse()


class DummyEmptyTitleGeminiModel:
    def generate_content(self, *args, **kwargs):
        class R:
            text = "   "
        return R()


def test_generate_series_title_returns_clean_title():
    engine = object.__new__(GeminiStoryEngine)
    engine._model = DummyTitleGeminiModel()

    title = engine.generate_series_title("horror", "You hear your own voice.", "A short story.")

    assert title == "The Sleepwood Tapes"


def test_generate_series_title_raises_on_empty_response():
    engine = object.__new__(GeminiStoryEngine)
    engine._model = DummyEmptyTitleGeminiModel()

    import pytest
    with pytest.raises(ValueError):
        engine.generate_series_title("horror", "You hear your own voice.", "A short story.")


def test_concept_tags_avoid_generic_false_positives():
    engine = object.__new__(GeminiStoryEngine)

    generic_text = "It was time to open the door with a key and check the phone battery."
    assert "clock_time" not in engine._concept_tags(generic_text)
    assert "door_lock" not in engine._concept_tags(generic_text)
    assert "phone_call" not in engine._concept_tags(generic_text)

    specific_text = (
        "At midnight, the locked door rattled while a voicemail played from an unknown number."
    )
    tags = engine._concept_tags(specific_text)
    assert "clock_time" in tags
    assert "door_lock" in tags
    assert "phone_call" in tags
