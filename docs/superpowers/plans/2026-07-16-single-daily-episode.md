# Single Daily Episode Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the daily schedule to a single series-episode slot (1 post/day), skip
posting entirely on gap days with no active/startable series, and confirm playlist
wiring stays correct.

**Architecture:** No new services. Add one read-only method to the existing
`SeriesService` (`app/services/series_service.py`) that the existing `DailyScheduler`
(`app/services/scheduler.py`) calls before creating a `Short` row, to decide whether
today's series slot has anything postable. Schedule collapse itself is a config/env
change, not code.

**Tech Stack:** Python, SQLAlchemy ORM (existing `Short`, `StorySeries`,
`SeriesEpisode` models), pytest, APScheduler (unchanged).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-16-single-daily-episode-design.md`
- Gap-day behavior: skip posting entirely (no `Short` row, no `Pipeline.run`, no
  Telegram notification) — log at INFO only.
- New-series gate stays Monday-only (`_is_series_start_day`) — do not change this.
- Schedule collapse is env-var driven (`SCHEDULE_TIMES=12:10`), not hardcoded in
  `scheduler.py` — must remain trivially reversible by editing the env var alone.
- `SERIES_SLOT_TIME` stays `12:10` (already the default in `app/core/config.py`).
- Playlist logic (`ensure_playlist`, `add_video_to_playlist`,
  `SeriesService.ensure_playlist_id`/`get_playlist_id`) is already correct — do not
  modify it, only verify via existing tests.
- Local `.env` and the Render dashboard env vars are NOT currently in sync — both must
  be updated for this to take effect in production; this plan can only change the local
  `.env`/`.env.example`, the Render dashboard change is a manual step for the user.
- Test command for this area:
  `pytest tests/test_scheduler.py tests/test_series_service.py -q`

---

### Task 1: Add `SeriesService.has_active_or_startable_series`

**Files:**
- Modify: `app/services/series_service.py`
- Test: `tests/test_series_service.py`

**Interfaces:**
- Consumes: existing `SeriesService._get_active_series(session) -> StorySeries | None`
  (already defined at `app/services/series_service.py:126`).
- Produces: `SeriesService.has_active_or_startable_series(session, allow_new_series: bool) -> bool`
  — used by Task 2's scheduler change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_series_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_series_service.py -k has_active_or_startable_series -v`
Expected: FAIL with `AttributeError: 'SeriesService' object has no attribute 'has_active_or_startable_series'`

- [ ] **Step 3: Implement the method**

In `app/services/series_service.py`, add this public method to `SeriesService` (place it
near `get_playlist_id`, e.g. directly after it at line 112):

```python
    def has_active_or_startable_series(self, session, allow_new_series: bool) -> bool:
        active = self._get_active_series(session)
        if active:
            return True
        return allow_new_series
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series_service.py -v`
Expected: all PASS (including the 3 new tests and the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add app/services/series_service.py tests/test_series_service.py
git commit -m "feat: add SeriesService.has_active_or_startable_series"
```

---

### Task 2: Skip scheduled job entirely on gap days

**Files:**
- Modify: `app/services/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `SeriesService.has_active_or_startable_series(session, allow_new_series) -> bool`
  from Task 1.
- Produces: `DailyScheduler._run_daily_job(is_series_slot: bool = False)` gains gap-day
  skip behavior; no signature change, so `scheduler.start()`'s job registration
  (`app/services/scheduler.py:79-88`) is untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scheduler.py`:

```python
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
```

Note: this also requires `DailyScheduler` to expose a `self.series` attribute (added in
Step 3) so tests can mock it directly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scheduler.py -k "skips_when_series_slot or runs_when_series_slot" -v`
Expected: FAIL with `AttributeError: 'DailyScheduler' object has no attribute 'series'`

- [ ] **Step 3: Implement the skip check**

In `app/services/scheduler.py`, add the import and instance attribute, then reorder
`_run_daily_job` so `allow_new_series` is computed before the postability check:

```python
from app.services.series_service import SeriesService
```

In `DailyScheduler.__init__` (currently at `app/services/scheduler.py:29-31`):

```python
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=settings.SCHEDULE_TIMEZONE)
        self._run_lock = threading.Lock()
        self.series = SeriesService()
```

Replace `_run_daily_job` (currently `app/services/scheduler.py:144-178`) with:

```python
    def _run_daily_job(self, is_series_slot: bool = False):
        if not self._run_lock.acquire(blocking=False):
            logger.warning("Scheduled job skipped: previous run still in progress")
            return

        engine = get_engine(settings.DB_PATH)
        SessionFactory = get_session_factory(engine)
        session = SessionFactory()
        try:
            allow_new_series = is_series_slot and self._is_series_start_day()

            if is_series_slot and not self.series.has_active_or_startable_series(session, allow_new_series):
                logger.info(
                    "Scheduled job skipped: no active series and today is not a series-start day"
                )
                return

            niche = self._pick_niche(session)
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
Expected: all PASS, including the 2 new tests and every pre-existing scheduler test
(pre-existing tests set `_is_series_start_day` to return `True`, which combined with
`is_series_slot=True` makes `allow_new_series=True`, so `has_active_or_startable_series`
is never mocked to `False` for them — verify none of the pre-existing tests break; if
`scheduler.series.has_active_or_startable_series` is called with real `mock_session` in
those pre-existing tests, it will hit a `MagicMock` session that isn't a real DB session
— check whether `_get_active_series` chokes on it. If it does, the pre-existing tests
will need `scheduler.series.has_active_or_startable_series = MagicMock(return_value=True)`
added alongside their existing mocks; add this only if the run in this step shows a
failure, and re-run to confirm green afterward.)

- [ ] **Step 5: Commit**

```bash
git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: skip scheduled job entirely on series gap days"
```

---

### Task 3: Collapse schedule to a single daily slot and document it

**Files:**
- Modify: `.env`
- Modify: `.env.example`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 directly — this is a config/docs-only task, but it's
  the change that actually makes "1 post/day" true given Task 2's skip logic.
- Produces: nothing consumed by later tasks (this is the last task).

- [ ] **Step 1: Update local `.env`**

In `.env`, change:

```env
SCHEDULE_TIMES=00:00,04:48,09:36,14:24,19:12
```

to:

```env
SCHEDULE_TIMES=12:10
```

Leave `SERIES_SLOT_TIME` unset in `.env` (it isn't currently set there; `config.py`'s
default of `12:10` applies and now matches exactly).

- [ ] **Step 2: Update `.env.example`**

In `.env.example`, change:

```env
SCHEDULE_TIMES=00:00,04:48,09:36,14:24,19:12
```

to:

```env
# Single daily slot = 1 post/day (series episode only). To restore multiple
# daily posts, add more comma-separated HH:MM times back here.
SCHEDULE_TIMES=12:10
```

- [ ] **Step 3: Update `CLAUDE.md` scheduler docs**

In `CLAUDE.md`, under the `### app/services/scheduler.py` section's "Current behavior"
bullet list, add a line clarifying today's actual configuration and the gap-day skip:

Find:

```
- niches from `SCHEDULE_NICHES`
- upload behavior from `SCHEDULE_UPLOAD`
```

Replace with:

```
- niches from `SCHEDULE_NICHES`
- upload behavior from `SCHEDULE_UPLOAD`
- default configuration is now a single daily slot (`SCHEDULE_TIMES=12:10`), i.e. the
  series-episode slot only; the other 3 legacy slots are paused, not removed — restore
  them by adding more comma-separated times to `SCHEDULE_TIMES`
- on a gap day (previous series completed, not yet Monday) the job is skipped entirely:
  no `Short` row, no pipeline run, no Telegram notification, just an INFO log line
  (`SeriesService.has_active_or_startable_series`)
```

Also update the `Scheduler variables` env block later in `CLAUDE.md` — find:

```
SCHEDULE_TIMES=00:10,06:10,12:10,18:10
SERIES_SLOT_TIME=12:10
```

Replace with:

```
SCHEDULE_TIMES=12:10
SERIES_SLOT_TIME=12:10
```

- [ ] **Step 4: Verify no code depends on the removed schedule times**

Run: `pytest tests/test_scheduler.py tests/test_series_service.py tests/test_pipeline.py -q`
Expected: all PASS (these tests patch `settings.SCHEDULE_TIMES` per-test where needed and
don't rely on the `.env` file's actual value)

- [ ] **Step 5: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: collapse default schedule to single daily episode slot"
```

Note: `.env` is gitignored and intentionally excluded from this commit — verify with
`git status` that `.env` does not appear as staged/tracked before committing.

- [ ] **Step 6: Manual step (not code) — update Render dashboard**

Remind the user: the Render dashboard's `SCHEDULE_TIMES` env var (and `SERIES_SLOT_TIME`
if set there) must be updated to match `12:10` directly in the Render UI — this repo's
`render.yaml` does not declare either var, so no file in this repo can make this change
for production. This step has no automated verification; confirm with the user once done.

---

## Final Verification

- [ ] Run the full focused suite: `pytest tests/test_gemini_story_engine.py tests/test_render_service.py tests/test_pipeline.py tests/test_youtube_service.py tests/test_scheduler.py tests/test_series_service.py -q`
- [ ] Expected: all PASS
- [ ] Confirm playlist behavior unchanged: re-read `app/services/pipeline.py:153-169` and
  confirm no lines were touched by Tasks 1-3.
