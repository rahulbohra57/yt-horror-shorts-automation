# Weekly Horror Story Series + Freshness Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing (currently dead-code) series/playlist system into production so 1 of the 4 daily shorts is a weekly 5-6 episode story series with cliffhanger endings and a Gemini-generated show name, and harden content-freshness checks so all shorts (series and standalone) stop feeling repetitive.

**Architecture:** `app/services/scheduler.py`'s fixed daily cron jobs gain a "series slot" concept; that slot calls the existing `Pipeline.run(series_mode=True, allow_new_series=<is Monday>)`. `SeriesService` gates new-series creation on `allow_new_series` and gains a `rename_series` method. `GeminiStoryEngine` gains an `is_final_episode` flag (cliffhanger prompt/CTA for non-final episodes), a `generate_series_title` call (premise-based series naming after episode 1), an expanded trope-tag list, and a title/hook dedup check fed by a broadened cross-niche history query in `Pipeline`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (SQLite), APScheduler 3.10, `google-generativeai` (Gemini), pytest 8.

## Global Constraints

- `SERIES_EPISODE_RANGE` (in `app/services/series_service.py`) is `(5, 6)` — series run 5-6 episodes.
- A new series may only start when `allow_new_series` is `True`, which the scheduler sets only on Monday (`datetime.now(ZoneInfo(settings.SCHEDULE_TIMEZONE)).weekday() == 0`).
- Series slot time defaults to `12:10` via a new `SERIES_SLOT_TIME` setting; if that time isn't among the configured `SCHEDULE_TIMES`, the earliest configured time is used instead.
- Novelty history queries: recent scripts lookback raises from 40 to 80 and drops the same-niche filter (cross-niche). Recent title/hook lookback is 200, also cross-niche.
- Near-duplicate title/hook detection threshold: token-overlap ratio `>= 0.9` counts as a duplicate.
- Non-final series episodes force the CTA to `CTA_BUCKETS["cliffhanger"]` (existing pool in `gemini_story_engine.py`); final episodes and standalone shorts keep today's general CTA selection.
- No database schema changes — all fields already exist on `StorySeries`/`SeriesEpisode`/`Short`.
- Follow existing test patterns: `object.__new__(GeminiStoryEngine)` + manually set attributes for engine unit tests (see `tests/test_gemini_story_engine.py`); `unittest.mock.patch` + `MagicMock`/`AsyncMock` for pipeline/scheduler tests (see `tests/test_pipeline.py`); real SQLite via `app.core.database.init_db(tmp_path / "test.db")` for anything that needs real ORM query behavior (see `tests/test_database.py`).

---

### Task 1: `SeriesService` — Monday gate, 5-6 episode range, `rename_series`

**Files:**
- Modify: `app/services/series_service.py:7` (episode range), `app/services/series_service.py:31-61` (`assign_short`)
- Test: `tests/test_series_service.py` (new)

**Interfaces:**
- Produces: `SeriesService.assign_short(session, short, allow_new_series: bool = True) -> SeriesAssignment | None` (new `allow_new_series` param, default `True` preserves old behavior for any other caller). `SeriesService.rename_series(session, series_id: int, new_name: str) -> None` (new method).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_series_service.py`:

```python
from app.core.database import init_db, get_session_factory
from app.core.models import JobStatus, Short, SeriesStatus, StorySeries
from app.services.series_service import SeriesService, SERIES_EPISODE_RANGE


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_series_service.py -v`
Expected: `test_episode_range_is_five_or_six` FAILs (range is currently `(4, 5)`); `test_assign_short_returns_none_when_no_active_series_and_new_series_not_allowed` FAILs with `TypeError: assign_short() got an unexpected keyword argument 'allow_new_series'`; `test_rename_series_...` FAILs with `AttributeError: 'SeriesService' object has no attribute 'rename_series'`.

- [ ] **Step 3: Implement the change**

In `app/services/series_service.py`, change line 7:

```python
SERIES_EPISODE_RANGE = (5, 6)
```

Replace `assign_short` (lines 31-44) with:

```python
    def assign_short(self, session, short: Short, allow_new_series: bool = True) -> SeriesAssignment | None:
        active = self._get_active_series(session)
        if active is None:
            if not allow_new_series:
                return None
            active = self._maybe_start_new_series(session, short.niche)
        if active is None:
            return None
        if short.niche != active.niche:
            short.niche = active.niche
```

(The rest of `assign_short`, from `current_count = self._episode_count(...)` onward, is unchanged.)

Add `rename_series` as a new method, placed after `get_playlist_id` (after line 110):

```python
    def rename_series(self, session, series_id: int, new_name: str) -> None:
        new_name = (new_name or "").strip()
        if not new_name:
            return
        series = session.query(StorySeries).filter(StorySeries.id == series_id).first()
        if not series:
            return
        series.name = new_name
        series.title_prefix = new_name
        series.playlist_name = f"{new_name} Series"
        session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/series_service.py tests/test_series_service.py
git commit -m "feat: gate new series creation and add series renaming"
```

---

### Task 2: `GeminiStoryEngine` — cliffhanger endings for non-final series episodes

**Files:**
- Modify: `app/services/gemini_story_engine.py:247-254` (`generate`), `:261-263` (fallback call), `:282-290` (`_generate_with_fallback` signature), `:295-306` and `:317-328` (fallback call sites), `:366-376` (`_call_gemini` signature), `:397-464` (prompt body + CTA choice)
- Test: `tests/test_gemini_story_engine.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `GeminiStoryEngine.generate(..., is_final_episode: bool = True)`, `_generate_with_fallback(..., is_final_episode: bool = True)`, `_call_gemini(..., is_final_episode: bool = True)` — all default `True` so every existing standalone-short call site is unaffected.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gemini_story_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gemini_story_engine.py -v -k cliffhanger`
Expected: FAIL with `TypeError: _call_gemini() got an unexpected keyword argument 'is_final_episode'`

- [ ] **Step 3: Implement the change**

In `app/services/gemini_story_engine.py`, update `generate` (lines 247-254):

```python
    def generate(
        self,
        niche: str,
        recent_scripts: Iterable[str] | None = None,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        is_final_episode: bool = True,
    ) -> dict:
```

Update the call inside `generate` (lines 261-263):

```python
        hook, script, cta, title_seed, scene_queries = self._generate_with_fallback(
            niche, recent, motif, series_context, series_episode_number, series_name, is_final_episode
        )
```

Update `_generate_with_fallback` signature (lines 282-290):

```python
    def _generate_with_fallback(
        self,
        niche: str,
        recent: list[str],
        motif: str,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        is_final_episode: bool = True,
    ) -> tuple[str, str, str, str, list]:
```

In the Tier 1 loop (lines 295-306), add `is_final_episode=is_final_episode,` to the `_call_gemini` kwargs:

```python
        for attempt in range(1, 6):
            try:
                return self._call_gemini(
                    niche=niche,
                    recent_scripts=recent,
                    motif=motif,
                    series_context=series_context,
                    series_episode_number=series_episode_number,
                    series_name=series_name,
                    blocked_tags_override=blocked_tags,
                    overlap_fail_count=2,
                    is_final_episode=is_final_episode,
                )
```

In the Tier 2 loop (lines 317-328), add the same kwarg:

```python
                try:
                    result = self._call_gemini(
                        niche=niche,
                        recent_scripts=recent,
                        motif=motif,
                        series_context=series_context,
                        series_episode_number=series_episode_number,
                        series_name=series_name,
                        blocked_tags_override=relaxed_blocked_tags,
                        overlap_fail_count=3,
                        is_final_episode=is_final_episode,
                    )
```

Update `_call_gemini` signature (lines 366-376):

```python
    def _call_gemini(
        self,
        niche: str,
        recent_scripts: list[str],
        motif: str = "",
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        blocked_tags_override: set[str] | None = None,
        overlap_fail_count: int = 2,
        is_final_episode: bool = True,
    ) -> tuple[str, str, str, str]:
```

Right after `format_instruction = random.choice(STORY_FORMATS)` (line 397), insert the cliffhanger variable computation:

```python
        format_instruction = random.choice(STORY_FORMATS)
        is_cliffhanger_episode = bool(series_context.strip()) and not is_final_episode
        if is_cliffhanger_episode:
            ending_requirement = (
                "* End on a CLIFFHANGER, not a resolved twist — cut away at the moment of "
                "maximum tension, right as the threat or mystery is about to be revealed. Do "
                "NOT explain or resolve what is happening. The viewer must feel the story is "
                "unfinished and urgently want to know what happens next."
            )
            beat4_instruction = (
                "4. **Cliffhanger Cutoff (50-60 sec):** Escalate to the single most tense "
                "moment, then STOP mid-threat. No resolution, no twist reveal — just dread and "
                "an open question."
            )
        else:
            ending_requirement = (
                "* End with an **unexpected twist ending** that reframes everything — the "
                "final line must be the most memorable and creepy line in the whole story."
            )
            beat4_instruction = (
                "4. **Twist Ending (50-60 sec):** Single gut-punch line that reframes "
                "everything. Must be the shortest, most memorable sentence in the story."
            )
```

Replace line 428 (`* End with an **unexpected twist ending**...`) with `{ending_requirement}` and replace line 441 (`4. **Twist Ending (50-60 sec):**...`) with `{beat4_instruction}`, so the prompt f-string reads (only the two changed lines shown, rest of the prompt is unchanged):

```python
* Include 1 main character only (unless necessary).
* Use a MIX of character names — American (Jake, Emma, Ryan, Sarah, Tyler, Ashley, Michael, Jessica, Chris, Melissa), British (Oliver, Charlotte, Harry, Amelia, James, Sophie, George, Lily, Thomas, Isabelle), or Indian (Riya, Arjun, Meera, Kabir, Priya, Dev, Ananya, Vikram). Do NOT always use Indian names — vary nationality each story.
* Story should feel realistic at first, then become deeply disturbing.
{ending_requirement}
* Story format for this generation: {format_instruction}
```

and:

```python
### 4-Beat Structure (strict):

1. **Hook (0–5 sec):** One or two short punchy sentences. Impossible situation. Immediate dread.
2. **Build-up (5–40 sec):** Strange events escalate. Each sentence raises the stakes. Longer sentences build pressure.
3. **Reveal (40–50 sec):** The terrifying truth surfaces. Short sharp sentences increase pace.
{beat4_instruction}
```

Finally, update the CTA selection. Replace line 490 (`cta = self._choose_cta(niche)`) with:

```python
        cta = random.choice(CTA_BUCKETS["cliffhanger"]) if is_cliffhanger_episode else self._choose_cta(niche)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gemini_story_engine.py -v`
Expected: PASS (all tests, including the 3 new ones and the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add app/services/gemini_story_engine.py tests/test_gemini_story_engine.py
git commit -m "feat: cliffhanger endings and CTA for non-final series episodes"
```

---

### Task 3: `GeminiStoryEngine.generate_series_title` — premise-based series naming

**Files:**
- Modify: `app/services/gemini_story_engine.py` (new method, place after `generate` and before `_generate_with_fallback`, i.e. after line 280)
- Test: `tests/test_gemini_story_engine.py`

**Interfaces:**
- Produces: `GeminiStoryEngine.generate_series_title(niche: str, hook: str, script: str) -> str`. Raises `ValueError` on empty/invalid output — caller (Task 6) must catch this and keep the placeholder name.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gemini_story_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gemini_story_engine.py -v -k generate_series_title`
Expected: FAIL with `AttributeError: 'GeminiStoryEngine' object has no attribute 'generate_series_title'`

- [ ] **Step 3: Implement the change**

In `app/services/gemini_story_engine.py`, add this method after `generate` (after line 280, before `_generate_with_fallback`):

```python
    def generate_series_title(self, niche: str, hook: str, script: str) -> str:
        prompt = (
            "You are naming a new horror/mystery YouTube Shorts story series based on its "
            "first episode.\n"
            f"Genre: {niche}\n"
            f"Episode 1 hook: {hook}\n"
            f"Episode 1 story: {script}\n\n"
            "Create ONE short, catchy series title (2-5 words) that sounds like a real "
            "streaming show name, grounded in this episode's premise, setting, or central "
            "object/threat. Do NOT use generic words like 'Horror Series' or 'Episode'. "
            "No quotes, no markdown, no trailing punctuation.\n\n"
            "Respond with ONLY the title text, nothing else."
        )
        response = self._model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.9, max_output_tokens=32),
        )
        title = (response.text or "").strip()
        title = re.sub(r'["\'`*_]+', "", title)
        title = re.sub(r"\s+", " ", title).strip(" .,:;-")
        if not title or len(title) > 60:
            raise ValueError(f"Invalid series title generated: '{title}'")
        return title
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gemini_story_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/gemini_story_engine.py tests/test_gemini_story_engine.py
git commit -m "feat: generate premise-based series titles via Gemini"
```

---

### Task 4: Expand `CONCEPT_KEYWORDS` for broader trope detection

**Files:**
- Modify: `app/services/gemini_story_engine.py:185-198` (`CONCEPT_KEYWORDS`)
- Test: `tests/test_gemini_story_engine.py`

**Interfaces:**
- Produces: `CONCEPT_KEYWORDS` dict with additional keys — consumed by existing `_concept_tags`/`_recent_concept_tags`/`_enforce_concept_freshness` (unchanged logic, just a bigger dict).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gemini_story_engine.py`:

```python
def test_expanded_concept_tags_catch_new_tropes():
    engine = object.__new__(GeminiStoryEngine)

    text = (
        "The old tape recording played back a voice from the hospital hallway, right after "
        "the car broke down outside the hotel and the power went out with a burst of static."
    )
    tags = engine._concept_tags(text)

    assert "tape_recording" in tags
    assert "hospital" in tags
    assert "car_breakdown" in tags
    assert "hotel_room" in tags
    assert "power_outage" in tags
    assert "static_noise" in tags
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gemini_story_engine.py -v -k expanded_concept_tags`
Expected: FAIL — `assert "tape_recording" in tags` fails since the tag doesn't exist yet.

- [ ] **Step 3: Implement the change**

In `app/services/gemini_story_engine.py`, replace `CONCEPT_KEYWORDS` (lines 185-198) with:

```python
CONCEPT_KEYWORDS = {
    "mirror": ["mirror", "reflection", "glass"],
    "phone_call": ["phone call", "voicemail", "unknown number", "ringing phone"],
    "chat_message": ["text", "message", "chat", "notification"],
    "basement": ["basement", "cellar", "underground"],
    "door_lock": ["locked door", "deadbolt", "door chain", "jammed lock", "spare key"],
    "camera_feed": ["camera", "cctv", "security feed", "monitor"],
    "clock_time": ["3:33", "midnight", "2:17 am", "03:00 am", "countdown timer"],
    "dead_contact": ["dead", "funeral", "grave", "obituary"],
    "haunted_object": ["box", "doll", "portrait", "object", "artifact"],
    "memory_manipulation": ["memory", "remember", "forgot", "imagined", "proof"],
    "ritual_curse": ["ritual", "curse", "symbol", "demon", "entity"],
    "home_intrusion": ["footsteps", "hallway", "closet", "attic", "window"],
    "social_media": ["social media", "instagram", "livestream", "followers", "comment section"],
    "photograph_letter": ["photograph", "photo", "polaroid", "handwritten letter", "old note"],
    "power_outage": ["power went out", "power outage", "lights flickered off", "blackout"],
    "static_noise": ["static", "white noise", "radio static", "buzzing on the line"],
    "hospital": ["hospital", "er room", "hospital bed", "nurse station"],
    "car_breakdown": ["car broke down", "engine stalled", "flat tire", "stranded on the road"],
    "hotel_room": ["hotel room", "motel", "hotel hallway", "front desk clerk"],
    "webcam_stream": ["webcam", "laptop camera", "video call", "screen recording"],
    "tape_recording": ["tape recording", "cassette", "recorder", "voice memo"],
    "doppelganger": ["doppelganger", "exact copy", "looked exactly like", "impostor"],
    "missing_time": ["missing time", "lost hours", "gap in memory", "hours had passed"],
    "family_secret": ["family secret", "adopted", "biological father", "hidden sibling"],
    "forest_isolation": ["forest", "woods", "hiking trail", "cabin in the woods"],
    "wedding_object": ["wedding ring", "engagement ring", "wedding dress", "bridal"],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gemini_story_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/gemini_story_engine.py tests/test_gemini_story_engine.py
git commit -m "feat: expand concept-tag list for broader repetition detection"
```

---

### Task 5: Title/hook dedup enforcement

**Files:**
- Modify: `app/services/gemini_story_engine.py` — `generate` (post-Task-2 signature), `_generate_with_fallback` (post-Task-2 signature), `_call_gemini` (post-Task-2 signature + body near lines 483-510)
- Test: `tests/test_gemini_story_engine.py`

**Interfaces:**
- Consumes: `is_final_episode` param and prompt structure from Task 2.
- Produces: `generate(..., recent_titles: Iterable[str] | None = None, recent_hooks: Iterable[str] | None = None)`, same additions on `_generate_with_fallback` and `_call_gemini`. New pure helpers: `_normalize_for_dedup(text: str) -> str`, `_is_near_duplicate(a: str, b: str, threshold: float = 0.9) -> bool`, `_enforce_title_hook_freshness(hook: str, title: str, recent_hooks: list[str], recent_titles: list[str]) -> None` (raises `ValueError` on a duplicate — consumed by Task 6's `Pipeline`, which relies on this raising to trigger the existing retry ladder).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gemini_story_engine.py`:

```python
def test_normalize_for_dedup_strips_punctuation_and_case():
    engine = object.__new__(GeminiStoryEngine)
    assert engine._normalize_for_dedup("The Attic Locket Had A Heartbeat!") == "the attic locket had a heartbeat"


def test_is_near_duplicate_detects_high_token_overlap():
    engine = object.__new__(GeminiStoryEngine)
    a = "You hear knocking from inside your own walls."
    b = "You hear knocking from inside your walls."
    assert engine._is_near_duplicate(a, b) is True


def test_is_near_duplicate_allows_distinct_text():
    engine = object.__new__(GeminiStoryEngine)
    a = "You hear knocking from inside your own walls."
    b = "The babysitter called about kids you never had."
    assert engine._is_near_duplicate(a, b) is False


def test_enforce_title_hook_freshness_raises_on_duplicate_title():
    engine = object.__new__(GeminiStoryEngine)
    import pytest
    with pytest.raises(ValueError):
        engine._enforce_title_hook_freshness(
            hook="A brand new hook line nobody has used before.",
            title="The Attic Locket Had A Heartbeat",
            recent_hooks=[],
            recent_titles=["The Attic Locket Had A Heartbeat"],
        )


def test_enforce_title_hook_freshness_passes_on_distinct_content():
    engine = object.__new__(GeminiStoryEngine)
    engine._enforce_title_hook_freshness(
        hook="A brand new hook line nobody has used before.",
        title="A Completely Different Title",
        recent_hooks=["You hear knocking from inside your own walls."],
        recent_titles=["The Attic Locket Had A Heartbeat"],
    )


def test_call_gemini_retries_are_triggered_by_duplicate_hook():
    engine = object.__new__(GeminiStoryEngine)
    engine._niches = {"horror": {}}
    engine._model = DummySeriesGeminiModel()

    import pytest
    with pytest.raises(ValueError):
        engine._call_gemini(
            "horror",
            [],
            recent_hooks=["You hear your own voice through the baby monitor."],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gemini_story_engine.py -v -k "dedup or duplicate or freshness"`
Expected: FAIL with `AttributeError: 'GeminiStoryEngine' object has no attribute '_normalize_for_dedup'` (and similar for the other new methods/params).

- [ ] **Step 3: Implement the change**

In `app/services/gemini_story_engine.py`, update `generate` signature (from Task 2) to add two more trailing params:

```python
    def generate(
        self,
        niche: str,
        recent_scripts: Iterable[str] | None = None,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        is_final_episode: bool = True,
        recent_titles: Iterable[str] | None = None,
        recent_hooks: Iterable[str] | None = None,
    ) -> dict:
```

Update the call inside `generate` to pass them through:

```python
        hook, script, cta, title_seed, scene_queries = self._generate_with_fallback(
            niche, recent, motif, series_context, series_episode_number, series_name,
            is_final_episode, list(recent_titles or []), list(recent_hooks or []),
        )
```

Update `_generate_with_fallback` signature to add the same two params:

```python
    def _generate_with_fallback(
        self,
        niche: str,
        recent: list[str],
        motif: str,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        is_final_episode: bool = True,
        recent_titles: list[str] | None = None,
        recent_hooks: list[str] | None = None,
    ) -> tuple[str, str, str, str, list]:
```

In both the Tier 1 and Tier 2 `_call_gemini(...)` call sites inside `_generate_with_fallback`, add:

```python
                    recent_titles=recent_titles,
                    recent_hooks=recent_hooks,
```

as additional kwargs (alongside `is_final_episode=is_final_episode,` added in Task 2).

Update `_call_gemini` signature to add the same two params:

```python
    def _call_gemini(
        self,
        niche: str,
        recent_scripts: list[str],
        motif: str = "",
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        blocked_tags_override: set[str] | None = None,
        overlap_fail_count: int = 2,
        is_final_episode: bool = True,
        recent_titles: list[str] | None = None,
        recent_hooks: list[str] | None = None,
    ) -> tuple[str, str, str, str]:
```

Inside `_call_gemini`, extend the `avoid_block` construction (right after the existing `blocked_tags` block, before `format_instruction = random.choice(STORY_FORMATS)`):

```python
        recent_titles = recent_titles or []
        recent_hooks = recent_hooks or []
        if recent_titles:
            avoid_block += (
                "\n\nTITLE FRESHNESS: Do NOT reuse or closely resemble any of these previously "
                "used titles: " + "; ".join(t[:70] for t in recent_titles[:20])
            )
        if recent_hooks:
            avoid_block += (
                "\n\nHOOK FRESHNESS: Do NOT reuse or closely resemble any of these previously "
                "used hook sentences: " + "; ".join(h[:100] for h in recent_hooks[:20])
            )
```

After `title_seed` is determined (right after the line `title_seed = random.choice(valid_titles) if valid_titles else (title_candidates[0] or "")`, around line 500) and before `scene_queries = ...`, add the freshness check:

```python
        self._enforce_title_hook_freshness(hook, title_seed, recent_hooks, recent_titles)
```

Add the three new helper methods, placed after `_enforce_concept_freshness` (after line 582, before `_is_concept_overlap_error`):

```python
    def _normalize_for_dedup(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9\s]", "", (text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_near_duplicate(self, a: str, b: str, threshold: float = 0.9) -> bool:
        tokens_a = set(self._normalize_for_dedup(a).split())
        tokens_b = set(self._normalize_for_dedup(b).split())
        if not tokens_a or not tokens_b:
            return False
        overlap = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
        return overlap >= threshold

    def _enforce_title_hook_freshness(
        self, hook: str, title: str, recent_hooks: list[str], recent_titles: list[str]
    ) -> None:
        normalized_hook = self._normalize_for_dedup(hook)
        for prior_hook in recent_hooks:
            if normalized_hook and (
                normalized_hook == self._normalize_for_dedup(prior_hook)
                or self._is_near_duplicate(hook, prior_hook)
            ):
                raise ValueError(f"Hook too similar to a recently used hook: '{prior_hook[:80]}'")

        normalized_title = self._normalize_for_dedup(title)
        for prior_title in recent_titles:
            if normalized_title and (
                normalized_title == self._normalize_for_dedup(prior_title)
                or self._is_near_duplicate(title, prior_title)
            ):
                raise ValueError(f"Title too similar to a recently used title: '{prior_title[:80]}'")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gemini_story_engine.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/gemini_story_engine.py tests/test_gemini_story_engine.py
git commit -m "feat: block reused titles and hooks via cross-niche dedup check"
```

---

### Task 6: `Pipeline` — wire series flags, broaden history, rename on episode 1

**Files:**
- Modify: `app/services/pipeline.py:8-16` (imports), `:60` (`run` signature), `:70-124` (assignment/history/generate block)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `SeriesService.assign_short(..., allow_new_series=...)` (Task 1), `GeminiStoryEngine.generate(..., is_final_episode=..., recent_titles=..., recent_hooks=...)` (Tasks 2 & 5), `GeminiStoryEngine.generate_series_title(...)` (Task 3), `SeriesService.rename_series(...)` (Task 1).
- Produces: `Pipeline.run(..., allow_new_series: bool = False)`, plus new static/instance helpers `Pipeline._load_recent_context(session, job_id) -> tuple[list[str], list[str], list[str]]`, `Pipeline._compute_is_final_episode(assignment) -> bool`, `Pipeline._maybe_rename_series(session, job_id, assignment, effective_niche, story) -> SeriesAssignment | None` — consumed only within `Pipeline.run` itself, but exposed as testable units.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
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
    from unittest.mock import MagicMock
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
    from unittest.mock import MagicMock
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
    from unittest.mock import MagicMock
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


def test_run_forwards_allow_new_series_to_series_assignment():
    from app.core.models import JobStatus
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
```

Add `from unittest.mock import patch` if not already imported at the top of `tests/test_pipeline.py` — check the existing import line (`from unittest.mock import AsyncMock, MagicMock, patch`) already covers this.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `AttributeError: type object 'Pipeline' has no attribute '_compute_is_final_episode'` and similar for `_load_recent_context`, `_maybe_rename_series`; the `allow_new_series` test fails with `TypeError: run() got an unexpected keyword argument 'allow_new_series'`.

- [ ] **Step 3: Implement the change**

In `app/services/pipeline.py`, update the import line (line 16):

```python
from app.services.series_service import SeriesService, SeriesAssignment
```

Update `run` signature (line 60):

```python
    async def run(self, niche: str, job_id: str, session, upload: bool = True, series_mode: bool = False, allow_new_series: bool = False) -> dict:
```

Update the assignment block (lines 74-89) to pass `allow_new_series`:

```python
            assignment = None
            continuity_context = ""
            effective_niche = niche
            if short and series_mode:
                try:
                    assignment = self.series.assign_short(session, short, allow_new_series=allow_new_series)
                    effective_niche = short.niche
                    if assignment:
                        continuity_context = self.series.get_series_continuity_context(
                            session,
                            assignment.series_id,
                            assignment.episode_number,
                        )
                        logger.info(
                            "[%s] Assigned to series='%s' episode=%s/%s",
                            job_id, assignment.series_name, assignment.episode_number, assignment.planned_episodes,
                        )
                except Exception as series_err:
                    logger.warning("[%s] Series assignment skipped: %s", job_id, series_err)

            is_final_episode = self._compute_is_final_episode(assignment)
```

Replace the recent-scripts loading block (lines 94-113) with a call to the new helper:

```python
            recent_scripts, recent_titles, recent_hooks = self._load_recent_context(session, job_id)
```

Update the `story = self.story.generate(...)` call (lines 115-121):

```python
            story = self.story.generate(
                effective_niche,
                recent_scripts=recent_scripts,
                series_context=continuity_context,
                series_episode_number=assignment.episode_number if assignment else None,
                series_name=assignment.series_name if assignment else "",
                is_final_episode=is_final_episode,
                recent_titles=recent_titles,
                recent_hooks=recent_hooks,
            )
            if assignment:
                assignment = self._maybe_rename_series(session, job_id, assignment, effective_niche, story)
                story = self._apply_series_title_prefix(story, assignment.title_prefix, assignment.episode_number)
            story = self._ensure_cta_in_script(story)
```

Add the three new helper methods after `_ensure_cta_in_script` (after line 242, before `_apply_series_title_prefix`):

```python
    @staticmethod
    def _load_recent_context(session, job_id: str) -> tuple[list[str], list[str], list[str]]:
        recent_scripts: list[str] = []
        try:
            rows = (
                session.query(Short.script)
                .filter(Short.script.isnot(None), Short.id != int(job_id))
                .order_by(Short.created_at.desc())
                .limit(80)
                .all()
            )
            for row in rows:
                if isinstance(row, str):
                    recent_scripts.append(row)
                elif isinstance(row, (tuple, list)) and row:
                    recent_scripts.append(row[0])
                else:
                    value = getattr(row, "script", None)
                    if value:
                        recent_scripts.append(value)
        except Exception as history_err:
            logger.warning(f"[{job_id}] Failed to load recent scripts: {history_err}")

        recent_titles: list[str] = []
        recent_hooks: list[str] = []
        try:
            meta_rows = (
                session.query(Short.title, Short.hook)
                .filter(Short.id != int(job_id))
                .order_by(Short.created_at.desc())
                .limit(200)
                .all()
            )
            for title_val, hook_val in meta_rows:
                if title_val:
                    recent_titles.append(title_val)
                if hook_val:
                    recent_hooks.append(hook_val)
        except Exception as meta_err:
            logger.warning(f"[{job_id}] Failed to load recent titles/hooks: {meta_err}")

        return recent_scripts, recent_titles, recent_hooks

    @staticmethod
    def _compute_is_final_episode(assignment) -> bool:
        return assignment is None or assignment.episode_number >= assignment.planned_episodes

    def _maybe_rename_series(self, session, job_id: str, assignment, effective_niche: str, story: dict):
        if not assignment or assignment.episode_number != 1:
            return assignment
        try:
            new_name = self.story.generate_series_title(effective_niche, story["hook"], story["script"])
            self.series.rename_series(session, assignment.series_id, new_name)
            return SeriesAssignment(
                series_id=assignment.series_id,
                series_name=new_name,
                title_prefix=new_name,
                playlist_name=f"{new_name} Series",
                episode_number=assignment.episode_number,
                planned_episodes=assignment.planned_episodes,
            )
        except Exception as rename_err:
            logger.warning(f"[{job_id}] Series rename skipped: {rename_err}")
            return assignment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (all tests, including pre-existing `test_pipeline_update_status_on_failure`)

- [ ] **Step 5: Run the full focused suite to check for regressions**

Run: `pytest tests/test_gemini_story_engine.py tests/test_render_service.py tests/test_pipeline.py tests/test_youtube_service.py tests/test_series_service.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire series flags, cross-niche history, and episode-1 renaming into Pipeline"
```

---

### Task 7: Scheduler — fixed series slot + Monday-only new-series gate

**Files:**
- Modify: `app/core/config.py:17-22` (new setting), `app/services/scheduler.py` (imports, `_series_slot`, `start`, `_run_daily_job`, `_is_series_start_day`)
- Test: `tests/test_scheduler.py` (new)

**Interfaces:**
- Consumes: `Pipeline.run(..., series_mode=..., allow_new_series=...)` from Task 6.
- Produces: `DailyScheduler._series_slot() -> tuple[int, int]`, `DailyScheduler._is_series_start_day(now: datetime | None = None) -> bool`, `DailyScheduler._run_daily_job(is_series_slot: bool = False)` — no other module depends on these.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler.py`:

```python
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


async def _async_none_coro():
    return None


def _async_none():
    return _async_none_coro()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL — `AttributeError: 'DailyScheduler' object has no attribute '_series_slot'` (and similarly for `_is_series_start_day`; the `_run_daily_job` tests fail with `TypeError: _run_daily_job() got an unexpected keyword argument 'is_series_slot'`).

- [ ] **Step 3: Implement the change**

In `app/core/config.py`, add a new setting after `SCHEDULE_TIMES` (line 18):

```python
    SCHEDULE_TIMES: str = "00:00,04:48,09:36,14:24,19:12"
    SERIES_SLOT_TIME: str = "12:10"
```

In `app/services/scheduler.py`, update the imports at the top (lines 1-10) to add `datetime` and `ZoneInfo`:

```python
import asyncio
import logging
import random
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.core.database import get_engine, get_session_factory
from app.core.models import Short, JobStatus
from app.services.pipeline import Pipeline
```

Add `_series_slot` and `_is_series_start_day` methods, placed after `_niches` (after line 54):

```python
    def _series_slot(self) -> tuple[int, int]:
        times = self._parse_schedule_times()
        raw = (settings.SERIES_SLOT_TIME or "").strip()
        try:
            hour_str, minute_str = raw.split(":")
            candidate = (int(hour_str), int(minute_str))
            if candidate in times:
                return candidate
        except Exception:
            pass
        return times[0]

    def _is_series_start_day(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(ZoneInfo(settings.SCHEDULE_TIMEZONE))
        return current.weekday() == 0
```

Replace `start` (lines 56-68) to mark which registered job is the series slot:

```python
    def start(self):
        series_slot = self._series_slot()
        for hour, minute in self._parse_schedule_times():
            job_id = f"scheduled_short_{hour:02d}{minute:02d}"
            is_series_slot = (hour, minute) == series_slot
            self.scheduler.add_job(
                self._run_daily_job,
                args=[is_series_slot],
                trigger=CronTrigger(hour=hour, minute=minute),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=settings.SCHEDULE_MISFIRE_GRACE_SECONDS,
            )
        self.scheduler.start()
        readable = ", ".join(f"{h:02d}:{m:02d}" for h, m in self._parse_schedule_times())
        logger.info(
            "Scheduler started: times=%s timezone=%s niches=%s upload=%s series_slot=%02d:%02d",
            readable,
            settings.SCHEDULE_TIMEZONE,
            self._niches(),
            settings.SCHEDULE_UPLOAD,
            series_slot[0], series_slot[1],
        )
```

Replace `_run_daily_job` (lines 122-150):

```python
    def _run_daily_job(self, is_series_slot: bool = False):
        if not self._run_lock.acquire(blocking=False):
            logger.warning("Scheduled job skipped: previous run still in progress")
            return

        engine = get_engine(settings.DB_PATH)
        SessionFactory = get_session_factory(engine)
        session = SessionFactory()
        try:
            niche = self._pick_niche(session)
            allow_new_series = is_series_slot and self._is_series_start_day()
            logger.info(
                "Scheduled job triggered: niche=%s series_slot=%s allow_new_series=%s",
                niche, is_series_slot, allow_new_series,
            )
            short = Short(niche=niche, status=JobStatus.PENDING)
            session.add(short)
            session.commit()
            session.refresh(short)
            pipeline = Pipeline()
            asyncio.run(
                pipeline.run(
                    niche=niche,
                    job_id=str(short.id),
                    session=session,
                    upload=settings.SCHEDULE_UPLOAD,
                    series_mode=is_series_slot,
                    allow_new_series=allow_new_series,
                )
            )
        except Exception as e:
            logger.error(f"Scheduled job failed: {e}", exc_info=True)
        finally:
            session.close()
            self._run_lock.release()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Update CLAUDE.md scheduler env var docs**

In `CLAUDE.md`, under the "Scheduler variables" code block, add the new setting:

```env
SCHEDULER_ENABLED=false
SCHEDULE_TIMES=00:10,06:10,12:10,18:10
SERIES_SLOT_TIME=12:10
SCHEDULE_TIMEZONE=Asia/Kolkata
SCHEDULE_UPLOAD=true
SCHEDULE_NICHES=horror,mystery,paranormal,twist_endings,psychological,supernatural,slasher,folk_horror
SCHEDULE_MISFIRE_GRACE_SECONDS=3600
```

- [ ] **Step 6: Run the full focused suite**

Run: `pytest tests/test_gemini_story_engine.py tests/test_render_service.py tests/test_pipeline.py tests/test_youtube_service.py tests/test_series_service.py tests/test_scheduler.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/core/config.py app/services/scheduler.py tests/test_scheduler.py CLAUDE.md
git commit -m "feat: fixed weekly series slot with Monday-only new-series gate"
```

---

## Post-implementation smoke check

After all 7 tasks are committed, run the broader suite once to confirm nothing else regressed:

```bash
pytest -q
```

There is no way to test the actual Gemini/YouTube calls without live credentials — the `series_mode`/`allow_new_series` wiring should be verified once against real credentials via a manual dry run before relying on it in production:

```bash
python scripts/run_scheduled_job.py --niche horror --upload false --mode series
```
