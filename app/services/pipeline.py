import asyncio
import logging
import random
from app.core.config import settings
from app.core.models import JobStatus, Short
from app.services.story_engine import StoryEngine
from app.services.pexels_service import PexelsService
from app.services.tts_service import TTSService
from app.services.render_service import RenderService
from app.services.youtube_service import YouTubeService

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self):
        self.story = StoryEngine()
        self.pexels = PexelsService(api_key=settings.PEXELS_API_KEY, cache_dir=settings.MEDIA_CACHE_DIR)
        self.tts = TTSService(output_dir=settings.OUTPUT_DIR + "/tts")
        self.renderer = RenderService(output_dir=settings.OUTPUT_DIR)
        self.youtube = YouTubeService(
            client_id=settings.YOUTUBE_CLIENT_ID,
            client_secret=settings.YOUTUBE_CLIENT_SECRET,
            refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
        )

    async def run(self, niche: str, job_id: str, session, upload: bool = True) -> dict:
        short = session.query(Short).filter_by(id=int(job_id)).first()

        def update_status(status, **kwargs):
            if short:
                short.status = status
                for k, v in kwargs.items():
                    setattr(short, k, v)
                session.commit()

        try:
            logger.info(f"[{job_id}] Generating story for niche={niche}")
            update_status(JobStatus.GENERATING)
            story = self.story.generate(niche)

            logger.info(f"[{job_id}] Generating TTS")
            audio_path, word_timings = await self.tts.generate(story["script"])

            logger.info(f"[{job_id}] Fetching Pexels videos (multi-scene)")
            pexels_queries = story.get("pexels_queries", [story["pexels_query"]])
            random.shuffle(pexels_queries)
            video_paths = []
            for q in pexels_queries[:6]:
                try:
                    videos = self.pexels.search_videos(q, count=2)
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
            video_path = self.renderer.render(video_paths, audio_path, story["script"], job_id, word_timings=word_timings, niche=niche)

            youtube_url = None
            if upload:
                logger.info(f"[{job_id}] Uploading to YouTube")
                update_status(JobStatus.UPLOADING)
                youtube_url = self.youtube.upload(video_path, story["seo"])

            update_status(JobStatus.DONE, video_path=video_path, youtube_url=youtube_url, title=story["title"])
            logger.info(f"[{job_id}] Pipeline complete. URL={youtube_url}")
            return {"status": "done", "youtube_url": youtube_url, "title": story["title"]}

        except Exception as e:
            logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
            update_status(JobStatus.FAILED, error_message=str(e)[:1000])
            return {"status": "failed", "error": str(e)}
