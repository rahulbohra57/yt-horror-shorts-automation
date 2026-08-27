import hashlib
import json
import logging
import random
import requests
import time
from pathlib import Path
from time import sleep
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
# Fetch more than needed so _extract_best can find count valid files even if some have no usable quality
_PEXELS_PER_PAGE = 15
# How long a Pexels video id is considered "recently used" and avoided in new picks
_USED_ID_RETENTION_SECONDS = 45 * 24 * 3600


class PexelsService:
    def __init__(self, api_key: str, cache_dir: str = "/tmp/pexels_cache"):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._used_ids_path = self.cache_dir / "used_video_ids.json"
        self._used_ids = self._load_used_ids()

    def _load_used_ids(self) -> dict:
        try:
            data = json.loads(self._used_ids_path.read_text())
        except Exception:
            return {}
        cutoff = time.time() - _USED_ID_RETENTION_SECONDS
        return {vid: ts for vid, ts in data.items() if ts >= cutoff}

    def _save_used_ids(self) -> None:
        try:
            self._used_ids_path.write_text(json.dumps(self._used_ids))
        except Exception:
            logger.debug("Failed to persist used Pexels video id cache", exc_info=True)

    def search_videos(self, query: str, count: int = 3) -> list[dict]:
        if not self.api_key:
            raise ValueError("PEXELS_API_KEY is not set")

        page = random.randint(1, 3)
        url = self._build_url(query, orientation="portrait", page=page)
        results = self._fetch(url, count)
        if not results:
            url = self._build_url(query, orientation="landscape", page=page)
            results = self._fetch(url, count)
        if not results and page > 1:
            url = self._build_url(query, orientation="portrait", page=1)
            results = self._fetch(url, count)
        return results

    def download_video(self, video_url: str) -> str:
        cache_key = hashlib.sha256(video_url.encode()).hexdigest()
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
            except requests.HTTPError as e:
                cached_path.unlink(missing_ok=True)
                if e.response is not None and e.response.status_code < 500:
                    raise RuntimeError(f"Non-retriable HTTP {e.response.status_code}: {video_url}") from e
                logger.warning(f"Download attempt {attempt+1} server error: {e}")
            except Exception as e:
                cached_path.unlink(missing_ok=True)
                logger.warning(f"Download attempt {attempt+1} failed: {e}")
            if attempt < 2:
                sleep(2 ** attempt)
        raise RuntimeError(f"Failed to download video after 3 attempts: {video_url}")

    def _build_url(self, query: str, orientation: str = "portrait", page: int = 1) -> str:
        return (
            f"{PEXELS_VIDEO_URL}?query={quote_plus(query)}"
            f"&orientation={orientation}&per_page={_PEXELS_PER_PAGE}&size=medium&page={page}"
        )

    def _fetch(self, url: str, count: int) -> list[dict]:
        headers = {"Authorization": self.api_key}
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                return self._extract_best(data.get("videos", []), count)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code < 500:
                    logger.error(f"Pexels non-retriable error {e.response.status_code}: {e}")
                    return []
                logger.warning(f"Pexels fetch attempt {attempt+1} server error: {e}")
            except Exception as e:
                logger.warning(f"Pexels fetch attempt {attempt+1} failed: {e}")
            if attempt < 2:
                sleep(2 ** attempt)
        return []

    def _extract_best(self, videos: list, count: int) -> list[dict]:
        candidates = []
        for video in videos:  # scan full response — per_page is deliberately over-fetched
            best = self._pick_best_file(video.get("video_files", []))
            if best:
                candidates.append({
                    "id": video["id"],
                    "url": best["link"],
                    "width": best["width"],
                    "height": best["height"],
                })

        # Prefer videos not recently used elsewhere to avoid the same stock
        # footage resurfacing across unrelated uploads. Fall back to the full
        # pool if dedup would leave nothing usable.
        fresh = [c for c in candidates if str(c["id"]) not in self._used_ids]
        pool = fresh if fresh else candidates

        results = pool[:count]
        if results:
            now = time.time()
            for r in results:
                self._used_ids[str(r["id"])] = now
            self._save_used_ids()
        return results

    def _pick_best_file(self, files: list) -> dict | None:
        portrait = [f for f in files if f.get("height", 0) > f.get("width", 0)]
        landscape = [f for f in files if f.get("width", 0) >= f.get("height", 0)]
        pool = portrait if portrait else landscape
        pool = [f for f in pool if f.get("quality") in ("hd", "sd")]
        if not pool:
            return None
        return max(pool, key=lambda f: f.get("width", 0) * f.get("height", 0))
