import json
import random

import pytest

from app.core.database import get_session_factory, init_db
from app.core.models import JobStatus, SeriesEpisode, Short, StorySeries, SeriesStatus
from app.services.gemini_story_engine import (
    QUALITY_RELAXED,
    QUALITY_STRICT,
    GeminiStoryEngine,
)
from app.services.premise_bank import _BANK, pick_premise
from app.services.series_service import SeriesService


def _engine(reply=None):
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {"horror": {"ctas": ["Follow for more."]}}
    if reply is not None:
        class Model:
            prompts = []

            def generate_content(self, prompt, *args, **kwargs):
                self.prompts.append(prompt)

                class R:
                    text = json.dumps(reply)
                return R()
        engine._model = Model()
    return engine


def _reply(script="The wall began to breathe.", **extra):
    return {"hook": "The wall began to breathe.", "title": "The Breathing Wall", "script": script, **extra}


def test_premises_never_reuse_a_pair_while_unused_pairs_remain():
    rng = random.Random(7)
    recent, seen = [], set()
    bank = _BANK["niches"]["horror"]
    for _ in range(len(bank["settings"]) * len(bank["threats"])):
        premise = pick_premise("horror", recent, rng)
        pair = (premise["setting"], premise["threat"])
        assert pair not in seen
        seen.add(pair)
        recent.insert(0, premise)


def test_premise_stays_inside_its_genre():
    for _ in range(50):
        assert pick_premise("folk_horror")["setting"] in _BANK["niches"]["folk_horror"]["settings"]


def test_premise_rotates_narration_voice():
    rng = random.Random(3)
    recent = []
    for _ in range(30):
        premise = pick_premise("horror", recent, rng)
        assert premise["pov"] not in [p["pov"] for p in recent[:2]]
        recent.insert(0, premise)


def test_episode_one_gets_a_cliffhanger_without_prior_context():
    engine = _engine(_reply())
    draft = engine._call_gemini("horror", [], series_episode_number=1, is_final_episode=False)
    assert "Part 2" in draft.cta or "part 2" in draft.cta
    assert "CLIFFHANGER" in engine._model.prompts[-1]


def test_standalone_prompt_requires_a_complete_ending():
    engine = _engine(_reply())
    engine._call_gemini("horror", [])
    assert "must be COMPLETE" in engine._model.prompts[-1]
    assert "CLIFFHANGER" not in engine._model.prompts[-1]


def test_strict_mode_rejects_wrong_length():
    engine = _engine()
    with pytest.raises(ValueError, match="words"):
        engine._enforce_quality("Too short.", {}, "standalone", QUALITY_STRICT, "")


def _story(words=135):
    return " ".join(["dread"] * (words - 1)) + " ended."


def test_failed_review_blocks_strict_but_not_relaxed():
    engine = _engine({"passes": False, "reason": "Question never answered."})
    with pytest.raises(ValueError, match="never answered"):
        engine._enforce_quality(_story(), {}, "standalone", QUALITY_STRICT, "")
    engine._enforce_quality(_story(), {}, "standalone", QUALITY_RELAXED, "")


def test_broken_reviewer_does_not_block():
    engine = _engine()

    class Broken:
        def generate_content(self, *args, **kwargs):
            raise RuntimeError("down")
    engine._model = Broken()
    engine._enforce_quality(_story(), {}, "standalone", QUALITY_STRICT, "")


def test_story_cannot_end_mid_thought():
    engine = _engine()
    with pytest.raises(ValueError, match="mid-thought"):
        engine._enforce_quality(_story() + " And the.", {}, "standalone", QUALITY_STRICT, "")


def test_same_opening_is_rejected_for_standalone_only():
    engine = _engine()
    with pytest.raises(ValueError, match="opens like"):
        engine._enforce_opening_variety("You open the box.", ["You open your eyes."], False)
    engine._enforce_opening_variety("You open the box.", ["You open your eyes."], True)


def test_scenes_are_anchored_to_narration_words():
    story = "The door was open. Nobody had a key. Then the lights died."
    scenes = GeminiStoryEngine._locate_scenes(story, [
        {"first_words": "The door was open", "query": "door"},
        {"first_words": "Then the lights died", "query": "lights"},
    ])
    assert scenes == [{"query": "door", "word_index": 0}, {"query": "lights", "word_index": 8}]


def test_unmatched_scene_lands_between_its_neighbours():
    story = " ".join(f"w{i}" for i in range(30))
    scenes = GeminiStoryEngine._locate_scenes(story, [
        {"first_words": "w0 w1 w2", "query": "a"},
        {"first_words": "not in the story", "query": "b"},
        {"first_words": "w20 w21 w22", "query": "c"},
    ])
    assert [s["word_index"] for s in scenes] == [0, 10, 20]


def test_hook_card_length_limits():
    assert GeminiStoryEngine._clean_hook_card("It Knows Your Name") == "It Knows Your Name"
    assert GeminiStoryEngine._clean_hook_card("One") == ""
    assert GeminiStoryEngine._clean_hook_card("a b c d e f g h") == ""


def test_series_plan_shows_previous_current_and_next():
    bible = {
        "protagonist": "Mira",
        "central_question": "Who wrote the notes?",
        "final_truth": "She did.",
        "episodes": [
            {"number": n, "events": f"events{n}", "reveal": f"reveal{n}", "ending": f"ending{n}"}
            for n in range(1, 5)
        ],
    }
    text = GeminiStoryEngine.format_series_plan(bible, 2)
    assert "Episode 1 (already told)" in text and "ending1" in text
    assert "THIS EPISODE (2)" in text and "events2" in text
    assert "NEXT EPISODE (3)" in text and "ending3" in text
    assert "events4" not in text


def test_series_bible_rejects_wrong_episode_count():
    engine = _engine({"protagonist": "A", "central_question": "B", "final_truth": "C", "episodes": []})
    with pytest.raises(ValueError):
        engine.generate_series_bible("horror", pick_premise("horror"), 4)


def _session(tmp_path):
    return get_session_factory(init_db(str(tmp_path / "t.db")))()


def _add_series(session):
    series = StorySeries(
        name="X", niche="horror", title_prefix="X", playlist_name="X Series",
        planned_episodes=4, status=SeriesStatus.ACTIVE,
    )
    session.add(series)
    session.commit()
    return series


def test_continuity_includes_the_full_ending_without_the_cta(tmp_path):
    session = _session(tmp_path)
    series = _add_series(session)
    body = "Start of story. " + ("Middle sentence goes here. " * 40) + "The hatch began to open."
    cta = "Part 2 drops tomorrow."
    short = Short(niche="horror", status=JobStatus.DONE, script=f"{body} {cta}", cta=cta)
    session.add(short)
    session.commit()
    session.add(SeriesEpisode(series_id=series.id, short_id=short.id, episode_number=1))
    session.commit()

    context = SeriesService().get_series_continuity_context(session, series.id, 2)

    assert context.endswith("The hatch began to open.")
    assert cta not in context


def test_bible_round_trips(tmp_path):
    session = _session(tmp_path)
    series = _add_series(session)
    service = SeriesService()
    assert service.get_bible(session, series.id) is None
    service.save_bible(session, series.id, {"final_truth": "She did."})
    assert service.get_bible(session, series.id) == {"final_truth": "She did."}


def test_no_standalone_cta_promises_more_of_the_story():
    niches = json.load(open("app/templates/niches.json"))
    for data in niches.values():
        for cta in data.get("ctas", []):
            assert "just the beginning" not in cta.lower()


def test_title_keeps_apostrophes_inside_words():
    engine = _engine()
    assert engine._clean_title("What Was Inside Aarav's Bedroom") == "What Was Inside Aarav's Bedroom"
    assert engine._clean_title("'Stay Inside' Said The Note") == "Stay Inside Said The Note"


def test_series_title_rejects_a_truncated_single_word():
    class R:
        text = "a"

    class Model:
        def generate_content(self, *args, **kwargs):
            return R()
    engine = _engine()
    engine._model = Model()
    with pytest.raises(ValueError):
        engine.generate_series_title("horror", "A hook.", "A story.")


def test_story_falls_back_when_the_writing_model_is_out_of_quota():
    class Exhausted:
        def generate_content(self, *args, **kwargs):
            raise RuntimeError("429 You exceeded your current quota")

    class Working:
        def generate_content(self, *args, **kwargs):
            return "fallback reply"
    engine = _engine()
    engine._model = Exhausted()
    engine._fallback_model = Working()
    assert engine._generate_story_content("prompt", None) == "fallback reply"
