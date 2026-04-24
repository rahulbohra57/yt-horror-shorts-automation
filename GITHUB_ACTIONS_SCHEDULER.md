# GitHub Actions Scheduler (Option 2)

This setup runs full story generation + render + YouTube upload on GitHub-hosted runners (not on Render).

## Required GitHub Repository Secrets

- `PEXELS_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `CHANNEL_NAME` (optional display value)

## Workflow

File: `.github/workflows/scheduled_uploads.yml`

- Runs 4 times/day at UTC:
  - `10 0 * * *`
  - `10 6 * * *`
  - `10 12 * * *`
  - `10 18 * * *`
- Installs FFmpeg + dependencies.
- Runs `scripts/run_scheduled_job.py` to execute one full pipeline run.
- Persists SQLite history (`.data/shorts.db`) with GitHub cache so novelty scoring carries across runs.

## Manual run

Use **Run workflow** in GitHub Actions and optionally set:
- `niche`: `auto` / `horror` / `mystery`
- `upload`: `true` / `false`
