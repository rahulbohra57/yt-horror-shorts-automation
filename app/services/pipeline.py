import asyncio
import json
import logging
import random
import requests
import re
from app.core.config import settings
from app.core.models import JobStatus, Short
from app.services.gemini_story_engine import GeminiStoryEngine, GeminiFailedError
from app.services.pexels_service import PexelsService
from app.services.tts_service import TTSService
from app.services.render_service import RenderService
from app.services.youtube_service import YouTubeService
from app.services.telegram_service import TelegramService
from app.services.gdrive_service import GDriveService
from app.services.cloudinary_service import CloudinaryService
from app.services.image_service import ImageService
from app.services.series_service import SeriesService, SeriesAssignment

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self):
        if settings.GEMINI_API_KEY:
            logger.info("Gemini API key found — using GeminiStoryEngine")
            self.story = GeminiStoryEngine()
        else:
            raise RuntimeError("GEMINI_API_KEY is not set. Cannot start pipeline.")
        self.pexels = PexelsService(api_key=settings.PEXELS_API_KEY, cache_dir=settings.MEDIA_CACHE_DIR)
        self.tts = TTSService(output_dir=settings.OUTPUT_DIR + "/tts")
        self.renderer = RenderService(output_dir=settings.OUTPUT_DIR)
        self.youtube = YouTubeService(
            client_id=settings.YOUTUBE_CLIENT_ID,
            client_secret=settings.YOUTUBE_CLIENT_SECRET,
            refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
        )
        self.telegram = TelegramService(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
        )
        self.gdrive = None
        if settings.GDRIVE_SERVICE_ACCOUNT_JSON and settings.GDRIVE_FOLDER_ID:
            try:
                self.gdrive = GDriveService(
                    service_account_json=settings.GDRIVE_SERVICE_ACCOUNT_JSON,
                    folder_id=settings.GDRIVE_FOLDER_ID,
                )
            except Exception as gdrive_init_err:
                logger.warning(f"GDriveService init failed (non-fatal): {gdrive_init_err}")
        self.cloudinary = (
            CloudinaryService(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
            )
            if settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET
            else None
        )
        self.series = SeriesService()
        self.images = (
            ImageService(
                api_key=settings.GEMINI_API_KEY,
                model=settings.AI_STILL_MODEL,
                output_dir=settings.OUTPUT_DIR + "/stills",
            )
            if settings.AI_STILLS_ENABLED
            else None
        )

    async def run(self, niche: str, job_id: str, session, upload: bool = True, series_mode: bool = False, allow_new_series: bool = False) -> dict:
        short = session.query(Short).filter_by(id=int(job_id)).first()

        def update_status(status, **kwargs):
            if short:
                short.status = status
                for k, v in kwargs.items():
                    setattr(short, k, v)
                session.commit()

        try:
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

            logger.info(f"[{job_id}] Generating story for niche={effective_niche}")
            update_status(JobStatus.GENERATING)
            await self.telegram.notify_started(effective_niche, job_id)
            recent_scripts, recent_titles, recent_hooks = self._load_recent_context(session, job_id)
            recent_premises = self._load_recent_premises(session, job_id)

            series_premise = None
            if assignment:
                bible = self._ensure_series_bible(
                    session, job_id, assignment, effective_niche, recent_premises, continuity_context,
                )
                if bible:
                    series_premise = bible["premise"]
                    plan_text = self.story.format_series_plan(bible, assignment.episode_number)
                    continuity_context = f"{plan_text}\n\n{continuity_context}".strip()

            story = self.story.generate(
                effective_niche,
                recent_scripts=recent_scripts,
                series_context=continuity_context,
                series_episode_number=assignment.episode_number if assignment else None,
                series_name=assignment.series_name if assignment else "",
                is_final_episode=is_final_episode,
                recent_titles=recent_titles,
                recent_hooks=recent_hooks,
                recent_premises=recent_premises,
                premise=series_premise,
            )
            if assignment:
                assignment = self._maybe_rename_series(session, job_id, assignment, effective_niche, story)
                story = self._apply_series_title_prefix(story, assignment.title_prefix, assignment.episode_number)
            story = self._ensure_cta_in_script(story)

            logger.info(f"[{job_id}] Generating TTS")
            audio_path, word_timings, pacing = await self._narrate(story)

            logger.info(f"[{job_id}] Fetching Pexels videos (multi-scene)")
            video_paths, scene_clips = self._fetch_footage(job_id, story)
            if not video_paths:
                raise RuntimeError("No videos could be fetched from Pexels")
            logger.info(f"[{job_id}] Downloaded {len(video_paths)} scene clips")

            logger.info(f"[{job_id}] Rendering video")
            update_status(JobStatus.RENDERING)
            video_path = self.renderer.render(
                video_paths, audio_path, story["script"], job_id,
                word_timings=word_timings,
                niche=effective_niche,
                cta=story.get("cta", ""),
                scenes=scene_clips,
                pacing=pacing,
                hook_card=story.get("hook_card", ""),
                story_format=story.get("story_format", ""),
                on_screen_text=story.get("on_screen_text", ""),
                end_card_text=self._end_card_text(assignment, is_final_episode),
            )

            youtube_url = None
            gdrive_url = None
            cloudinary_url = None
            if upload:
                logger.info(f"[{job_id}] Uploading to YouTube")
                update_status(JobStatus.UPLOADING)
                youtube_url = self.youtube.upload(video_path, story["seo"])
                if youtube_url:
                    await self.telegram.notify_uploaded(story["title"], youtube_url, effective_niche)
                    if assignment:
                        try:
                            playlist_id = self.series.get_playlist_id(session, assignment.series_id)
                            if not playlist_id:
                                playlist_id = self.youtube.ensure_playlist(
                                    assignment.playlist_name,
                                    description=(
                                        f"Story series: {assignment.series_name}. "
                                        f"Episodes continue in strict order."
                                    ),
                                )
                                self.series.ensure_playlist_id(session, assignment.series_id, playlist_id)
                            video_id = self._extract_video_id(youtube_url)
                            if video_id:
                                self.youtube.add_video_to_playlist(playlist_id, video_id)
                        except Exception as pl_err:
                            logger.warning(f"[{job_id}] Playlist update failed (non-fatal): {pl_err}")

                if self.cloudinary:
                    try:
                        logger.info(f"[{job_id}] Uploading to Cloudinary for Instagram relay")
                        cloudinary_url = self.cloudinary.upload(video_path, f"short_{job_id}")
                        logger.info(f"[{job_id}] Cloudinary URL: {cloudinary_url}")
                    except Exception as cd_err:
                        logger.warning(f"[{job_id}] Cloudinary upload failed (non-fatal): {cd_err}")

                if cloudinary_url and settings.MAKE_WEBHOOK_URL:
                    try:
                        logger.info(f"[{job_id}] Firing Make.com webhook")
                        resp = requests.post(
                            settings.MAKE_WEBHOOK_URL,
                            json={
                                "cloudinary_url": cloudinary_url,
                                "youtube_url": youtube_url,
                                "title": story["title"],
                                "niche": effective_niche,
                                "job_id": job_id,
                            },
                            timeout=15,
                        )
                        logger.info(f"[{job_id}] Webhook response: {resp.status_code}")
                    except Exception as wh_err:
                        logger.warning(f"[{job_id}] Make.com webhook failed (non-fatal): {wh_err}")


            update_status(
                JobStatus.DONE,
                video_path=video_path,
                youtube_url=youtube_url,
                title=story["title"],
                script=story["script"],
                hook=story["hook"],
                cta=story.get("cta", ""),
                pexels_query=story["pexels_query"],
                premise=json.dumps(story.get("premise")) if story.get("premise") else None,
            )
            logger.info(f"[{job_id}] Pipeline complete. YouTube={youtube_url} Cloudinary={cloudinary_url} GDrive={gdrive_url}")
            return {"status": "done", "youtube_url": youtube_url, "cloudinary_url": cloudinary_url, "gdrive_url": gdrive_url, "title": story["title"]}

        except GeminiFailedError as e:
            logger.error(f"[{job_id}] Gemini story generation failed: {e}", exc_info=True)
            update_status(JobStatus.FAILED, error_message=str(e)[:1000])
            await self.telegram.notify_gemini_failed(niche, str(e))
            return {"status": "failed", "error": str(e)}
        except Exception as e:
            logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
            update_status(JobStatus.FAILED, error_message=str(e)[:1000])
            await self.telegram.notify_failed(job_id, niche, str(e))
            return {"status": "failed", "error": str(e)}

    async def _narrate(self, story: dict) -> tuple[str, list, dict | None]:
        """Voice the story and CTA with a pause between them when they can be separated."""
        script = story["script"].strip()
        cta = (story.get("cta") or "").strip()
        if cta and script.endswith(cta) and len(script) > len(cta):
            body = script[: -len(cta)].strip()
            return await self.tts.generate_with_pause(body, cta)
        audio_path, word_timings = await self.tts.generate(script)
        return audio_path, word_timings, None

    def _download_first(self, job_id: str, query: str) -> str | None:
        try:
            for video in self.pexels.search_videos(query, count=1):
                return self.pexels.download_video(video["url"])
        except Exception as e:
            logger.warning(f"[{job_id}] Footage for '{query}' failed: {e}")
        return None

    def _fetch_footage(self, job_id: str, story: dict) -> tuple[list[str], list[dict]]:
        """One clip per story beat. Returns (all paths, scenes anchored to narration)."""
        scene_plan = story.get("scenes") or []
        all_queries = list(dict.fromkeys(story.get("pexels_queries") or [story["pexels_query"]]))
        spare_queries = [q for q in all_queries if q not in {s["query"] for s in scene_plan}]

        scene_clips: list[dict] = []
        for scene in scene_plan:
            path = self._download_first(job_id, scene["query"])
            while not path and spare_queries:
                path = self._download_first(job_id, spare_queries.pop(0))
            if path:
                scene_clips.append({"path": path, "word_index": scene["word_index"]})

        video_paths = [c["path"] for c in scene_clips]
        if not video_paths:
            for query in all_queries[:6]:
                path = self._download_first(job_id, query)
                if path:
                    video_paths.append(path)
            return video_paths, []

        self._insert_key_still(job_id, story, scene_clips, video_paths)
        return video_paths, scene_clips

    def _insert_key_still(self, job_id: str, story: dict, scene_clips: list[dict], video_paths: list[str]) -> None:
        key_visual = story.get("key_visual")
        if not self.images or not key_visual:
            return
        still = self.images.generate_still(key_visual["image_prompt"])
        if not still:
            return
        index = key_visual["word_index"]
        scene_clips[:] = [c for c in scene_clips if c["word_index"] != index]
        scene_clips.append({"path": still, "word_index": index})
        scene_clips.sort(key=lambda c: c["word_index"])
        video_paths.append(still)
        logger.info(f"[{job_id}] Added AI still at word {index}")

    @staticmethod
    def _end_card_text(assignment, is_final_episode: bool) -> str:
        if assignment and not is_final_episode:
            return f"PART {assignment.episode_number + 1}\nTOMORROW"
        return f"FOLLOW\n@{settings.CHANNEL_NAME}"

    def _ensure_series_bible(
        self, session, job_id: str, assignment, niche: str, recent_premises: list[dict], published: str,
    ) -> dict | None:
        """Load the series plan, creating it on episode 1 or for a series already running."""
        try:
            bible = self.series.get_bible(session, assignment.series_id)
            if bible:
                return bible
            premise = self.story.pick_premise(niche, recent_premises)
            bible = self.story.generate_series_bible(
                niche, premise, assignment.planned_episodes, published_episodes=published,
            )
            self.series.save_bible(session, assignment.series_id, bible)
            return bible
        except Exception as e:
            logger.warning(f"[{job_id}] Series plan unavailable, using earlier episodes only: {e}")
            return None

    @staticmethod
    def _load_recent_premises(session, job_id: str) -> list[dict]:
        """Premises already used, newest first, so new stories can avoid them."""
        try:
            rows = (
                session.query(Short.premise)
                .filter(Short.premise.isnot(None), Short.id != int(job_id))
                .order_by(Short.created_at.desc())
                .limit(200)
                .all()
            )
            return [json.loads(row[0]) for row in rows if row[0]]
        except Exception as e:
            logger.warning(f"[{job_id}] Failed to load recent premises: {e}")
            return []

    @staticmethod
    def _ensure_cta_in_script(story: dict) -> dict:
        """Guarantee the CTA is part of the script before TTS and captions run."""
        script = (story.get("script") or "").strip()
        cta = (story.get("cta") or "").strip()
        if cta and cta not in script:
            logger.warning("CTA missing from generated script; appending before TTS")
            story = {**story, "script": f"{script} {cta}".strip()}
        return story

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

    @staticmethod
    def _apply_series_title_prefix(story: dict, prefix: str, episode_number: int) -> dict:
        """Series episode titles are just "<Series Name> | Ep <N>" — the
        episode's own hook-based title is dropped in favor of the franchise
        name so the series reads as one continuous show in a viewer's feed."""
        title = (story.get("title") or "").strip()
        seo = story.get("seo") or {}
        core = f"{prefix} | Ep {episode_number}".strip()
        final_title = f"{core[:90].rstrip()} #Shorts"

        description = seo.get("description", "")
        if title and description.startswith(title):
            description = final_title + description[len(title):]
        new_seo = {**seo, "title": final_title, "description": description}
        return {**story, "title": final_title, "seo": new_seo}

    @staticmethod
    def _extract_video_id(youtube_url: str) -> str:
        if not youtube_url:
            return ""
        m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", youtube_url)
        return m.group(1) if m else ""
