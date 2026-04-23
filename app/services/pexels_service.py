import hashlib
import logging
import requests
from pathlib import Path
from time import sleep
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


class PexelsService:
    def __init__(self, api_key: str, cache_dir: str = "/tmp/pexels_cache"):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search_videos(self, query: str, count: int = 3) -> list[dict]:
        if not self.api_key:
            raise ValueError("PEXELS_API_KEY is not set")

        url = self._build_url(query, orientation="portrait")
        results = self._fetch(url, count)
        if not results:
            url = self._build_url(query, orientation="landscape")
            results = self._fetch(url, count)
        return results

    def download_video(self, video_url: str) -> str:
        cache_key = hashlib.md5(video_url.encode()).hexdigest()
        cached_path = self.cache_dir / f"{cache_key}.mp4"
        if cached_path.exists():
            logger.info(f"Cache hit: {cached_path}")
            return str(cached_path)

        logger.info(f"Downloading: {video_url}")
        for attempt in range(3):
            try:
                resp = requests.get(video_url, stream=True, timeout=60)
                resp.raise_for_status()
                with open(cached_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Downloaded to {cached_path}")
                return str(cached_path)
            except Exception as e:
                logger.warning(f"Download attempt {attempt+1} failed: {e}")
                sleep(2 ** attempt)
        raise RuntimeError(f"Failed to download video after 3 attempts: {video_url}")

    def _build_url(self, query: str, orientation: str = "portrait") -> str:
        return f"{PEXELS_VIDEO_URL}?query={quote_plus(query)}&orientation={orientation}&per_page=15&size=medium"

    def _fetch(self, url: str, count: int) -> list[dict]:
        headers = {"Authorization": self.api_key}
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                return self._extract_best(data.get("videos", []), count)
            except Exception as e:
                logger.warning(f"Pexels fetch attempt {attempt+1} failed: {e}")
                sleep(2 ** attempt)
        return []

    def _extract_best(self, videos: list, count: int) -> list[dict]:
        results = []
        for video in videos[:count * 2]:
            best = self._pick_best_file(video.get("video_files", []))
            if best:
                results.append({
                    "id": video["id"],
                    "url": best["link"],
                    "width": best["width"],
                    "height": best["height"],
                })
            if len(results) >= count:
                break
        return results

    def _pick_best_file(self, files: list) -> dict | None:
        portrait = [f for f in files if f.get("height", 0) > f.get("width", 0)]
        landscape = [f for f in files if f.get("width", 0) >= f.get("height", 0)]
        pool = portrait if portrait else landscape
        pool = [f for f in pool if f.get("quality") in ("hd", "sd")]
        return pool[0] if pool else None
