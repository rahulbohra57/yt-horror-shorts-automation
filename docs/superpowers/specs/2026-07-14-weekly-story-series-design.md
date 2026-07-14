# Weekly Horror Story Series + Freshness Overhaul — Design

## Context

The pipeline already has a partially-built series/playlist system (`app/core/models.py`: `StorySeries`, `SeriesEpisode`; `app/services/series_service.py`: `SeriesService`; playlist methods in `app/services/youtube_service.py`; wiring in `app/services/pipeline.py`), but it is **dead code**: `Pipeline.run(..., series_mode=False)` defaults to `False` and neither `app/services/scheduler.py` nor `app/api/routes.py` ever passes `series_mode=True`. Nothing in production currently creates a series or a playlist.

Separately, individual (non-series) shorts are reported as feeling repetitive — same tropes/openings recurring across videos.

This design wires up the series feature end-to-end and hardens content freshness for all shorts (series and standalone).

## Goals

1. Every day, 1 of the 4 scheduled shorts is a series episode; the other 3 are standalone.
2. Series run 5-6 episodes, one series active at a time, exactly one series per calendar week (starts Monday).
3. Each series gets a catchy, premise-based name and its own YouTube playlist.
4. Non-final episodes end on a cliffhanger with a "want the next part" CTA; the final episode fully resolves.
5. Standalone (and series) content stops feeling repetitive: broader novelty checks, no reused titles/hooks.

## Non-goals

- No changes to TTS, rendering, or upload mechanics.
- No admin UI for managing series (fully automatic).
- No retroactive backfill of playlists for shorts already published.

## 1. Scheduling — series slot + weekly cadence

`app/services/scheduler.py`:

- Add `SERIES_SLOT_HOUR`/`SERIES_SLOT_MINUTE` (default `12:10`, matching one of the existing `SCHEDULE_TIMES`). The daily job registered for that exact time runs in **series mode**; all other scheduled times run standalone exactly as today (`series_mode=False`).
- In the series-slot job:
  - Determine `is_monday` from `datetime.now(ZoneInfo(settings.SCHEDULE_TIMEZONE)).weekday() == 0`.
  - Pick the niche via the existing `_pick_niche()` rotation (unchanged), so a new series' niche still respects the round-robin/no-repeat logic.
  - Call `pipeline.run(niche=..., job_id=..., session=..., upload=..., series_mode=True, allow_new_series=is_monday)`.
- `SeriesService.assign_short(session, short, allow_new_series)`:
  - If an active series exists, assign the next episode as today (unchanged).
  - If no active series exists and `allow_new_series` is `False`, return `None` (pipeline falls back to a normal standalone short for that slot — this is the "off day" case, e.g. series finished early on a Thursday, no new series starts until next Monday).
  - If no active series exists and `allow_new_series` is `True`, start a new series (see §2) and assign episode 1.
- `SERIES_EPISODE_RANGE` changes from `(4, 5)` to `(5, 6)`.

Net effect: exactly one series is active per calendar week, always starting Monday, 5-6 episodes long; any days after a series completes (but before the next Monday) just run 4 standalone shorts that day.

## 2. Series identity — Gemini-generated, premise-based names

Today `SeriesService._series_name()` picks two random words from a fixed list (e.g. "Whisper Ledger S28-26"). This changes to a real, premise-derived name:

- `_maybe_start_new_series` creates the `StorySeries` row with a temporary placeholder name (e.g. `f"series-{short.id}"`) so episode 1 can generate without needing a name yet (episode 1 has no continuity context regardless).
- After episode 1's story is generated in `Pipeline.run`, call a new `GeminiStoryEngine.generate_series_title(niche, hook, script) -> str` — a small, separate Gemini call using the episode 1 hook/script to produce a 2-4 word show-style title (e.g. "The Sleepwood Tapes", "House on Cinder Lane"). Falls back to the existing random word-pair generator if this call fails.
- `SeriesService.rename_series(session, series_id, new_name)` updates `name`, `title_prefix`, and `playlist_name` (`f"{new_name} Series"`) on the `StorySeries` row. This happens before the YouTube playlist is created (playlist creation already happens later, at upload time), so the playlist is created with the real name from the start.
- Episode title format is unchanged: `f"{title_prefix} | Ep {episode_number}: {core_title} #Shorts"`.

## 3. Cliffhanger endings for non-final episodes

`GeminiStoryEngine.generate()` / `_call_gemini()` gain an `is_final_episode: bool = True` parameter. `Pipeline.run` computes it from the existing `SeriesAssignment`: `is_final_episode = assignment is None or assignment.episode_number >= assignment.planned_episodes`.

Prompt changes in `_call_gemini`, only active when `series_context` is non-empty and `is_final_episode` is `False`:

- Replace the "twist ending" instruction and the 4-beat structure's step 4 with cliffhanger-specific instructions: cut away at peak tension, leave the immediate threat/mystery unresolved, no reveal of the underlying truth yet.
- Force the CTA selection (`_choose_cta`) to draw from the existing `CTA_BUCKETS["cliffhanger"]` pool instead of the general niche/CTA pool, when `is_final_episode is False` and a series assignment exists.

Final episodes (`is_final_episode=True`) and all standalone shorts keep the current full-twist-resolution prompt and normal CTA pool, unchanged.

## 4. Freshness overhaul

All changes in `app/services/pipeline.py` and `app/services/gemini_story_engine.py`, applied to every short (series and standalone) since it's the shared generation path:

**Cross-niche recency window** (`pipeline.py`, `Pipeline.run`): drop the `Short.niche == effective_niche` filter from the recent-scripts query; raise `limit` from 40 to 80. Novelty/concept-overlap comparisons in `GeminiStoryEngine` now consider recent scripts across all niches, not just the current one.

**Expanded concept-tag list** (`gemini_story_engine.py`, `CONCEPT_KEYWORDS`): add roughly 12-15 new tags to catch more repeated tropes, e.g.: `social_media`, `photograph_letter`, `power_outage`, `static_noise`, `hospital`, `car_breakdown`, `hotel_room`, `webcam_stream`, `tape_recording`, `doppelganger`, `missing_time`, `family_secret`, `forest_isolation`, `wedding_object`. Same detection mechanism as existing tags (substring match against normalized script text).

**Hard title/hook dedup**: new query in `Pipeline.run` alongside the recent-scripts query, fetching recent `Short.title` and `Short.hook` (cross-niche, limit ~200). This list is:
1. Passed into `GeminiStoryEngine.generate()` as `recent_titles`/`recent_hooks` and injected into the prompt's existing "CRITICAL: do not start with..." block as additional exclusions.
2. Checked post-generation in `_call_gemini`: if the new `hook` or chosen `title` is an exact match (case-insensitive, normalized) or near-duplicate (e.g. >90% token overlap) of any recent title/hook, raise the same kind of retryable error used for concept overlap (`_enforce_concept_freshness` gets a sibling `_enforce_title_hook_freshness`), triggering the existing retry ladder (strict → relaxed → template fallback).

No schema changes required — `Short.title` and `Short.hook` already exist as columns.

## Data flow summary

```
Scheduler (series slot, e.g. 12:10)
  -> pick niche via existing rotation
  -> Pipeline.run(series_mode=True, allow_new_series=is_monday)
       -> SeriesService.assign_short(allow_new_series)
            -> active series? assign next episode
            -> no active series + Monday? create series (placeholder name), assign ep 1
            -> no active series + not Monday? return None (falls back to standalone path)
       -> is_final_episode = assignment is None or ep_number >= planned_episodes
       -> load recent scripts/titles/hooks (cross-niche, broader window)
       -> GeminiStoryEngine.generate(..., is_final_episode=...)
       -> if ep 1: GeminiStoryEngine.generate_series_title(...) -> SeriesService.rename_series(...)
       -> continue pipeline as today (TTS, Pexels, render, upload, playlist ensure/add)

Scheduler (other 3 slots)
  -> pick niche via existing rotation
  -> Pipeline.run(series_mode=False)  [unchanged, but benefits from freshness overhaul]
```

## Error handling

- `generate_series_title` failure: non-fatal, falls back to existing random word-pair name generator (logged as warning).
- Title/hook dedup check: follows existing retry-then-fallback pattern (strict retries -> relaxed retries -> deterministic template -> `GeminiFailedError`). No new failure mode introduced.
- Series assignment errors: already caught non-fatally in `Pipeline.run` (`except Exception as series_err`), unchanged — a series failure never blocks a short from publishing as standalone.

## Testing

- `tests/test_series_service.py` (new or extend if exists): Monday-gate behavior (`allow_new_series` True/False), episode range `(5,6)`, `rename_series`.
- `tests/test_gemini_story_engine.py`: cliffhanger prompt/CTA selection when `is_final_episode=False`, full-twist behavior when `True`, expanded concept tags catch new tropes, title/hook dedup rejects exact and near-duplicate matches, `generate_series_title` happy path + fallback.
- `tests/test_pipeline.py`: cross-niche recent-scripts query (no niche filter), `is_final_episode` computed correctly from assignment, series renaming invoked only on episode 1.
- `tests/test_scheduler.py` (new if not present): series slot always passes `series_mode=True`, other slots pass `False`, `allow_new_series` reflects weekday correctly.

Run before pushing:
```bash
pytest tests/test_gemini_story_engine.py tests/test_render_service.py tests/test_pipeline.py tests/test_youtube_service.py tests/test_series_service.py tests/test_scheduler.py -q
```
