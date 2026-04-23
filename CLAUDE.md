# CLAUDE.md

## Project: Free YouTube Shorts Story Automation Platform

### Objective
Build a **100% free**, end-to-end automation platform that creates and uploads viral-style YouTube Shorts based on short story series with strong hooks, emotional payoff, and retention-focused pacing.

Deployment target: **Render.com free tier**  
Media sources: **Pexels free stock videos/images only**  
Primary use case: Automated faceless Shorts channel growth.

---

## Core Product Requirements

### Functional Flow
1. User selects story niche/category:
   - Moral stories
   - Mystery stories
   - Horror micro stories
   - Motivation stories
   - Relationship drama
   - Historical facts with twist
   - AI generated fictional episodes

2. System automatically:
   - Generates story ideas in episodic series format
   - Writes script with **unexpected opening hook**
   - Splits scenes by timestamp
   - Fetches matching Pexels media
   - Generates AI voiceover (free TTS)
   - Adds subtitles/captions
   - Adds music/SFX (royalty free)
   - Renders vertical 9:16 Short
   - Generates SEO title, description, hashtags
   - Uploads to YouTube automatically
   - Stores analytics logs

---

## Virality Framework

### Hook Formula (first 2 seconds mandatory)
Use one of:
- “He opened the door... and froze.”
- “Nobody believed her until this happened.”
- “For 10 years, he hid one secret.”
- “This message arrived after she died.”
- “The last customer changed everything.”

### Retention Rules
- Sentence every 1–2 seconds
- Pattern interrupts every 5 seconds
- Curiosity gap maintained till final reveal
- Final twist or lesson
- Max duration: 20–35 seconds ideal

---

## Tech Stack (Free Only)

### Backend
- Python 3.11
- FastAPI

### Video Processing
- MoviePy
- FFmpeg

### AI / Text
- Local templates + optional Ollama local LLM support
- No paid APIs required

### TTS
Use free options:
- edge-tts
- gTTS fallback

### Media
- Pexels API

### Upload
- YouTube Data API v3

### Database
- SQLite

### Scheduler
- APScheduler / cron

### Hosting
- Render.com free web service

---

## Render Constraints
- Must support sleeping dyno/restart
- Use persistent disk if available
- Jobs must be resumable
- Store temp files in /tmp then cleanup
- Keep RAM under free-tier limits

---

## Required Pages

### Dashboard
- Start generation
- Upload queue
- Video history
- Channel analytics
- API key settings

### Templates
- Story prompts
- Hook presets
- Caption styles
- Niche packs

---

## Folder Structure

```txt
/app
  /api
  /core
  /services
    story_engine.py
    pexels_service.py
    tts_service.py
    render_service.py
    youtube_service.py
  /templates
  /static
  /db
main.py
requirements.txt
render.yaml
CLAUDE.md
```

---

## Key Modules

### story_engine.py
Generate:
- titles
- episodic scripts
- twists
- hooks
- CTA lines

### pexels_service.py
Search and download:
- portrait videos first
- fallback landscape crop center
- cache assets

### render_service.py
Combine:
- clips
- zoom motion
- subtitles
- transitions
- voiceover
- music

### youtube_service.py
Upload:
- title
- description
- tags
- Shorts visibility settings
- scheduled posting

---

## SEO Rules

### Title Formula
`She Found a Locked Box After 20 Years... #shorts`

### Description
- 2 keyword lines
- 1 curiosity line
- CTA subscribe line

### Tags
#shorts #story #viral #moralstory #ytshorts

---

## Automation Modes

### Fully Auto
Generate + render + upload daily.

### Semi Auto
Generate drafts for approval.

### Bulk Mode
Create 7 Shorts in one run.

---

## Quality Rules

- Captions always readable
- No black bars
- 1080x1920 output
- Loudness normalized
- First frame visually strong
- No copyrighted assets

---

## Free API Keys Needed

Environment variables:

```env
PEXELS_API_KEY=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
CHANNEL_NAME=
```

---

## Future Enhancements

- Multi-language Shorts
- Hindi voiceover mode
- Auto comments reply
- A/B title testing
- Analytics driven regeneration
- Telegram alerts

---

## Claude Coding Instructions

When generating code for this project:

1. Prefer modular Python architecture.
2. Keep all services independently testable.
3. Never use paid APIs unless optional.
4. Handle Render free-tier memory carefully.
5. Use async where useful.
6. Provide `.env.example`.
7. Add detailed logging.
8. Include retry logic for Pexels and YouTube upload.
9. Optimize render speed.
10. Keep setup beginner friendly.

---

## First Build Priority

1. FastAPI dashboard
2. Story generator
3. Pexels fetcher
4. TTS
5. FFmpeg vertical renderer
6. YouTube uploader
7. Daily scheduler

---

## Success Metric

Create 1 automated Short/day at zero recurring cost.
