# CLAUDE.md

## Project: YouTube Horror Shorts Automation

### Current Objective
Build and operate an automated YouTube Shorts pipeline for faceless horror/mystery storytelling. The current production flow generates a retention-focused story, creates voiceover, fetches matching stock video, renders a vertical short with captions and background music, uploads to YouTube, and stores job metadata.

Primary channel: `HorrorShorts57`  
Primary runtime: Python FastAPI service plus scheduled/manual pipeline jobs  
Deployment target: Render.com or GitHub Actions/manual runner  
Current production story engine: Gemini via `GeminiStoryEngine`

---

## Current Functional Flow

1. A job is created with a niche.
2. `Pipeline.run()` loads recent scripts for that niche from SQLite to reduce repetition.
3. `GeminiStoryEngine` generates:
   - opening hook
   - full 150-170 word story body
   - short clickable title seed
   - niche-aware SEO metadata
4. The engine appends a CTA from the controlled CTA pool.
5. The pipeline defensively verifies the CTA is included in the exact script sent to TTS.
6. `TTSService` generates voiceover and word timings with `edge-tts`.
7. `PexelsService` searches/downloads multiple video clips and uses cached assets when possible.
8. `RenderService` merges/crops clips to 1080x1920, adds captions, mixes background music, normalizes loudness, and writes an MP4.
9. `YouTubeService` uploads the rendered MP4 with title, description, tags, category, and Shorts metadata.
10. Optional integrations notify Telegram, upload Cloudinary for Instagram relay, and optionally use GDrive if configured correctly.

---

## Active Niches

Production niches live in `app/templates/niches.json` and are used by Gemini for Pexels query pools and niche CTA pools.

Current active schedule-friendly niches:
- `horror`
- `mystery`
- `paranormal`
- `twist_endings`
- `psychological`
- `supernatural`
- `slasher`
- `folk_horror`

Legacy `StoryEngine` and older tests may still reference older niches such as moral/motivation/relationship, but the current runtime pipeline requires `GEMINI_API_KEY` and uses `GeminiStoryEngine`.

---

## Retention And Story Rules

### First 10 Seconds
The first 10 seconds are critical. Gemini is instructed to:
- start the script with the exact hook sentence
- make the first 35 words contain immediate danger, a disturbing question, or an impossible discovery
- avoid slow setup, backstory, and filler

The code also enforces this with `_ensure_hook_starts_script()` so the spoken script starts with the hook even if Gemini drifts.

### Story Length
- Target story body: 150-170 words before CTA
- TTS rate: `+50%`
- The final script includes story plus CTA
- If Gemini ends mid-sentence, `_close_incomplete_sentence()` trims or completes the ending

### CTA Rules
- Gemini must not write CTAs directly.
- CTAs are selected by code after story generation.
- `GeminiStoryEngine._cta_pool_for(niche)` prefers niche-specific `ctas` from `app/templates/niches.json`.
- If a niche has no CTA pool, it falls back to the built-in `_CTA_POOL`.
- `Pipeline._ensure_cta_in_script()` is the final guard before TTS and rendering.

---

## Title, Hashtag, And SEO Rules

### Title Rules
Titles should be short, complete, and clickable.

Current behavior:
- Gemini returns a separate `title` field under 58 characters.
- `_generate_title()` sanitizes it and appends only `#Shorts`.
- Titles are capped under YouTube's 100-character limit.
- Titles should not be built by truncating long hook text.
- Titles should not contain broken multi-word genre hashtags like `#Psychological Horror`.

Good example:
```txt
The Attic Locket Had A Heartbeat #Shorts
```

Bad examples:
```txt
The Antique Locket I Found In The Attic Had A Perfect, Tiny #Psychological Horror #Shorts
The Door Opened And I Saw My Own Body Lying Beside The... #Shorts
```

### Description And Hashtags
SEO description comes from `SEO_CONFIGS` in `app/services/gemini_story_engine.py`.

Rules:
- Keep title at the top of the description.
- Keep hashtags as valid single tokens.
- Use lowercase compact hashtags in descriptions, such as `#psychologicalhorror`, not broken phrases.
- Include a channel CTA line with `@HorrorShorts57` or configured `CHANNEL_NAME`.
- Tags sent to YouTube are plain tag strings in `seo["tags"]`.

---

## Key Modules

### `app/services/pipeline.py`
Orchestrates the full job.

Responsibilities:
- create/update job status
- load recent scripts for novelty
- generate story metadata
- enforce CTA presence before TTS
- generate TTS
- fetch Pexels clips
- render video
- upload to YouTube if requested
- notify Telegram and optional services

Important guard:
```py
Pipeline._ensure_cta_in_script(story)
```

### `app/services/gemini_story_engine.py`
Current production story engine.

Responsibilities:
- Gemini prompt construction
- recent-opening avoidance
- JSON parsing from Gemini
- hook-start enforcement
- title sanitization
- CTA selection from niche pool
- SEO description and tags

Important methods:
- `_call_gemini()`
- `_ensure_hook_starts_script()`
- `_cta_pool_for()`
- `_append_cta()`
- `_generate_title()`
- `_generate_seo()`

### `app/services/story_engine.py`
Legacy template engine.

Keep it working for older tests and possible fallback experiments, but it is not the current runtime path in `Pipeline`.

### `app/services/tts_service.py`
Voiceover generation.

Current behavior:
- primary provider: `edge-tts`
- default voice: `en-US-GuyNeural`
- default rate: `+50%`
- returns `(audio_path, word_timings)`
- caches MP3 and JSON timing files by hash
- gTTS fallback only if `ALLOW_GTTS_FALLBACK` is enabled

### `app/services/pexels_service.py`
Searches and downloads free stock videos.

Current behavior:
- uses Pexels API
- prefers portrait-friendly videos when available
- caches downloads in `MEDIA_CACHE_DIR`
- removes partial files on failed downloads

### `app/services/render_service.py`
Renders final vertical video.

Current behavior:
- target: 1080x1920, 30fps
- merges multiple Pexels clips to match audio duration
- crops/scales to vertical 9:16
- adds captions from word timings when available
- uses subtitle/libass path when available, with Pillow overlay fallback
- mixes background music from `background_audio/Horror` or `background_audio/Mystery`
- normalizes loudness to approximately `-16 LUFS`

CTA/caption note:
- TTS receives the full script including CTA.
- Captions are generated from the same full script and word timings, so CTA should be spoken and captioned.

### `app/services/youtube_service.py`
Uploads rendered MP4 to YouTube.

Current behavior:
- OAuth refresh-token based YouTube upload
- privacy default: `public`
- category: Entertainment (`22`)
- title truncation hard cap: 100 characters
- resumable upload with progress logging and retries

### `app/services/scheduler.py`
Daily scheduler using APScheduler.

Current behavior:
- controlled by `SCHEDULER_ENABLED`
- scheduled times from `SCHEDULE_TIMES`
- timezone from `SCHEDULE_TIMEZONE`
- niches from `SCHEDULE_NICHES`
- upload behavior from `SCHEDULE_UPLOAD`

---

## Repository Structure

```txt
app/
  api/
    routes.py
    deps.py
  core/
    config.py
    database.py
    models.py
  services/
    pipeline.py
    gemini_story_engine.py
    story_engine.py
    pexels_service.py
    tts_service.py
    render_service.py
    youtube_service.py
    scheduler.py
    telegram_service.py
    cloudinary_service.py
    gdrive_service.py
  templates/
    niches.json
    hooks.json
    captions.json
  static/
    index.html
background_audio/
  Horror/
  Mystery/
scripts/
  run_scheduled_job.py
  telegram_commands.py
  telegram_poll.py
tests/
main.py
_run_pipeline.py
requirements.txt
render.yaml
CLAUDE.md
```

---

## Environment Variables

Core required variables:

```env
GEMINI_API_KEY=
PEXELS_API_KEY=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
CHANNEL_NAME=HorrorShorts57
DB_PATH=app/db/shorts.db
MEDIA_CACHE_DIR=/tmp/pexels_cache
OUTPUT_DIR=/tmp/shorts_output
```

Scheduler variables:

```env
SCHEDULER_ENABLED=false
SCHEDULE_TIMES=00:10,06:10,12:10,18:10
SCHEDULE_TIMEZONE=Asia/Kolkata
SCHEDULE_UPLOAD=true
SCHEDULE_NICHES=horror,mystery,paranormal,twist_endings,psychological,supernatural,slasher,folk_horror
SCHEDULE_MISFIRE_GRACE_SECONDS=3600
```

Optional integrations:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APP_URL=
YOUTUBE_API_KEY=
YOUTUBE_CHANNEL_HANDLE=
GDRIVE_SERVICE_ACCOUNT_JSON=
GDRIVE_FOLDER_ID=
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
MAKE_WEBHOOK_URL=
ALLOW_GTTS_FALLBACK=false
```

Operational note:
- Multiline JSON in `.env`, especially `GDRIVE_SERVICE_ACCOUNT_JSON`, can produce `python-dotenv` parse warnings if not escaped/quoted correctly. GDrive failures are currently non-fatal, but clean this up before relying on GDrive uploads.

---

## Local Commands

### Run Tests
Focused current-path suite:

```bash
pytest tests/test_gemini_story_engine.py tests/test_render_service.py tests/test_pipeline.py tests/test_youtube_service.py -q
```

Broader suite:

```bash
pytest -q
```

### Run One Full Pipeline Locally
Upload to YouTube:

```bash
python _run_pipeline.py horror true
```

Generate/render without YouTube upload:

```bash
python _run_pipeline.py horror false
```

### Run Scheduled Job Script

```bash
python scripts/run_scheduled_job.py --niche horror --upload true
```

### Start API Locally

```bash
uvicorn main:app --reload
```

---

## Recent Verified Behavior

A full manual pipeline run successfully completed with upload enabled.

Example result from job `39`:
- local video: `/tmp/shorts_output/39.mp4`
- YouTube URL: `https://youtube.com/shorts/uG_QUZeahFs`
- CTA included in saved script and generated before TTS
- CTA used: `Share this with someone brave enough to watch it alone tonight. New horror drops every single day.`

Latest deployed commit at time of this update:

```txt
ac4e360 Improve shorts CTA and metadata generation
```

---

## Deployment Workflow

Before pushing:

```bash
pytest tests/test_gemini_story_engine.py tests/test_render_service.py tests/test_pipeline.py tests/test_youtube_service.py -q
```

Commit and push:

```bash
git add <changed-files>
git commit -m "Short descriptive message"
git push origin main
```

Current remote:

```txt
origin https://github.com/rahulbohra57/yt-horror-shorts-automation.git
```

Do not commit secrets, `.env`, generated videos, TTS cache files, or downloaded Pexels cache files.

---

## Quality Checklist For Every Generated Short

- CTA is included in `story["script"]` before TTS.
- CTA is spoken and captioned at the end.
- Title is complete, catchy, and under 100 characters.
- Title only includes `#Shorts`, not broken genre hashtags.
- Description hashtags are valid compact tokens.
- First caption starts with the hook, not mid-story setup.
- First 10 seconds contain immediate danger, mystery, or an impossible discovery.
- Output is 1080x1920 with no black bars.
- Captions are readable and synced.
- Background music is low enough not to overpower narration.
- YouTube upload returns a Shorts URL.

---

## Coding Instructions For Future Agents

1. Treat `GeminiStoryEngine` as the production story path unless the user explicitly asks for legacy template behavior.
2. Keep services independently testable.
3. Preserve the CTA guard in both story generation and pipeline orchestration.
4. Do not let Gemini write CTAs directly; choose CTAs in code from controlled pools.
5. Keep title generation separate from hook generation.
6. Never add broken multi-word hashtags to titles.
7. Update or add tests when changing story generation, metadata, TTS, rendering, or upload behavior.
8. Avoid destructive git commands.
9. Do not commit `.env`, media cache, rendered MP4s, generated TTS files, or private credentials.
10. Prefer `rg` for code search and focused pytest commands for verification.

---

## Future Enhancements

- Fix `.env` handling for `GDRIVE_SERVICE_ACCOUNT_JSON`.
- Add automated post-upload metadata verification.
- Add A/B title generation and analytics feedback.
- Add safer profanity/copyright checks before upload.
- Add multi-language voiceover modes.
- Add Instagram relay via Cloudinary/Make.com hardening.
- Add stronger thumbnail/first-frame selection for Shorts preview.
