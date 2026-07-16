# Single Daily Episode Schedule — Design

## Goal

Pause the 3 non-series daily posting slots so `HorrorShorts57` posts only 1 video per
day: the series episode slot. Confirm/verify series-episode playlist behavior stays intact.

## Background

The scheduler (`app/services/scheduler.py`) currently registers one APScheduler job per
entry in `SCHEDULE_TIMES` (4 slots by default). Exactly one of those slots is designated
the "series slot" (`SERIES_SLOT_TIME`, matched against the configured times, falling back
to the earliest time if no match). Only the series slot runs with `series_mode=True`.

New series are only allowed to start on Mondays (`_is_series_start_day`). On any day the
series slot runs but there's no active series and it isn't Monday,
`SeriesService.assign_short()` returns `None`, and today's pipeline silently falls back to
generating a normal, non-series short — this is the "normal" posting we're pausing.

Playlist support (`ensure_playlist`, `add_video_to_playlist` in `youtube_service.py`,
wired into `pipeline.py` around the YouTube upload step, `playlist_id` cached per-series
via `SeriesService.ensure_playlist_id`/`get_playlist_id`) is already implemented and
working — each series gets one dedicated playlist, created on first episode upload, and
every subsequent episode is added to it. No changes needed here.

## Design

### 1. Schedule collapse (env-driven, reversible)

Set `SCHEDULE_TIMES` to a single value, `12:10`, in both:
- the local `.env` file
- the Render dashboard env vars (the two are NOT currently in sync — local `.env` has 5
  slots and no `12:10` entry at all, so the series slot is presently landing on `00:00`
  by fallback, not `12:10` as `CLAUDE.md` describes; production's actual value is whatever
  is set in the Render dashboard, which this repo can't see or change)

`SERIES_SLOT_TIME` stays `12:10` (already the default in `config.py` and `.env`). With
only one configured time, that time is automatically the series slot regardless of
`SERIES_SLOT_TIME`, since `_series_slot()` falls back to `times[0]` when there's no exact
match.

No code changes are required to collapse the schedule — restoring the old 4-slot
schedule later is just an env var edit, not a deploy.

### 2. Skip gap days entirely (new behavior)

Add a read-only method to `SeriesService`:

```py
def has_active_or_startable_series(self, session, allow_new_series: bool) -> bool:
    active = self._get_active_series(session)
    if active:
        return True
    return allow_new_series
```

In `scheduler.py`'s `_run_daily_job`, reorder so `allow_new_series` is computed first, then
— for the series slot only — check `has_active_or_startable_series` before creating a
`Short` row or invoking `Pipeline.run()`. If it returns `False` (previous series just
completed and today isn't Monday), log at INFO and return immediately: no `Short` row, no
pipeline run, no Telegram notification (confirmed: stay silent on gap days, just a log
line for debuggability).

This replaces today's implicit fallback (posting a normal one-off short when no series
assignment is possible) with "post nothing."

### 3. Playlists

No changes. Verified already wired end-to-end in `pipeline.py` and `series_service.py`.

## Testing

- Unit test for `SeriesService.has_active_or_startable_series`: active series → True;
  no active series + `allow_new_series=True` → True; no active series +
  `allow_new_series=False` → False.
- Unit/integration test for `scheduler._run_daily_job`: series slot with no postable
  series skips without creating a `Short` row or calling `Pipeline.run`.
- Existing scheduler/pipeline/series tests must continue to pass.

## Out of scope

- Any change to playlist logic (already correct).
- Changing the Monday-only new-series gate.
- Render dashboard env var change itself (operational step for the user, not code).
