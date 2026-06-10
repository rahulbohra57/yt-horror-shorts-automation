import asyncio
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
from app.services.series_service import SeriesService

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

    async def run(self, niche: str, job_id: str, session, upload: bool = True, series_mode: bool = False) -> dict:
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
                    assignment = self.series.assign_short(session, short)
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

            logger.info(f"[{job_id}] Generating story for niche={effective_niche}")
            update_status(JobStatus.GENERATING)
            await self.telegram.notify_started(effective_niche, job_id)
            recent_scripts = []
            try:
                rows = (
                    session.query(Short.script)
                    .filter(Short.niche == effective_niche, Short.script.isnot(None), Short.id != int(job_id))
                    .order_by(Short.created_at.desc())
                    .limit(40)
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

            story = self.story.generate(
                effective_niche,
                recent_scripts=recent_scripts,
                series_context=continuity_context,
                series_episode_number=assignment.episode_number if assignment else None,
                series_name=assignment.series_name if assignment else "",
            )
            if assignment:
                story = self._apply_series_title_prefix(story, assignment.title_prefix, assignment.episode_number)
            story = self._ensure_cta_in_script(story)

            logger.info(f"[{job_id}] Generating TTS")
            audio_path, word_timings = await self.tts.generate(story["script"])

            logger.info(f"[{job_id}] Fetching Pexels videos (multi-scene)")
            pexels_queries = story.get("pexels_queries", [story["pexels_query"]])
            # Use scene-specific queries first (Gemini provides 6), deduplicate, cap at 6
            seen_queries: set[str] = set()
            unique_queries = []
            for q in pexels_queries:
                if q not in seen_queries:
                    seen_queries.add(q)
                    unique_queries.append(q)
            video_paths = []
            for q in unique_queries[:6]:
                try:
                    videos = self.pexels.search_videos(q, count=1)
                    for v in videos:
                        try:
                            video_paths.append(self.pexels.download_video(v["url"]))
                        except Exception as dl_err:
                            logger.warning(f"[{job_id}] Video download failed for '{q}': {dl_err}")
                except Exception as q_err:
                    logger.warning(f"[{job_id}] Pexels query '{q}' failed: {q_err}")
            if not video_paths:
                raise RuntimeError("No videos could be fetched from Pexels")
            logger.info(f"[{job_id}] Downloaded {len(video_paths)} scene clips")

            logger.info(f"[{job_id}] Rendering video")
            update_status(JobStatus.RENDERING)
            video_path = self.renderer.render(video_paths, audio_path, story["script"], job_id, word_timings=word_timings, niche=niche, cta=story.get("cta", ""))

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
                pexels_query=story["pexels_query"],
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
    def _apply_series_title_prefix(story: dict, prefix: str, episode_number: int) -> dict:
        title = (story.get("title") or "").strip()
        seo = story.get("seo") or {}
        episode_marker = f"Ep {episode_number}"
        core_title = title.replace(" #Shorts", "").strip()
        prefixed = f"{prefix} | {episode_marker}: {core_title}".strip()
        final_title = f"{prefixed[:90].rstrip()} #Shorts"
        new_seo = {**seo, "title": final_title}
        return {**story, "title": final_title, "seo": new_seo}

    @staticmethod
    def _extract_video_id(youtube_url: str) -> str:
        if not youtube_url:
            return ""
        m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", youtube_url)
        return m.group(1) if m else ""
