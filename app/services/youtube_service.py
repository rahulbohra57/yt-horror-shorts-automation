import logging
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from time import sleep

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube"
CATEGORY_ENTERTAINMENT = "22"


class YouTubeService:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token

    def upload(self, video_path: str, seo: dict, privacy: str = "public") -> str:
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError("YouTube credentials not configured — set client_id, client_secret, refresh_token")

        service = self._get_service()
        body = self._build_request_body(seo, privacy)
        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=5 * 1024 * 1024)

        request = service.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        video_id = self._execute_upload(request)
        url = f"https://youtube.com/shorts/{video_id}"
        logger.info(f"Uploaded to YouTube: {url}")
        return url

    def ensure_playlist(self, name: str, description: str = "", privacy: str = "public") -> str:
        service = self._get_service()
        existing_id = self._find_playlist_id(service, name)
        if existing_id:
            return existing_id

        body = {
            "snippet": {"title": name[:150], "description": description[:5000]},
            "status": {"privacyStatus": privacy},
        }
        resp = service.playlists().insert(part="snippet,status", body=body).execute()
        playlist_id = resp.get("id")
        if not playlist_id:
            raise RuntimeError(f"Playlist creation failed for '{name}'")
        logger.info("Created YouTube playlist '%s' (%s)", name, playlist_id)
        return playlist_id

    def add_video_to_playlist(self, playlist_id: str, video_id: str) -> None:
        service = self._get_service()
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        service.playlistItems().insert(part="snippet", body=body).execute()
        logger.info("Added video %s to playlist %s", video_id, playlist_id)

    def _find_playlist_id(self, service, name: str) -> str | None:
        token = None
        wanted = (name or "").strip().lower()
        while True:
            resp = service.playlists().list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=token,
            ).execute()
            for item in resp.get("items", []):
                title = (item.get("snippet", {}).get("title") or "").strip().lower()
                if title == wanted:
                    return item.get("id")
            token = resp.get("nextPageToken")
            if not token:
                return None

    def _execute_upload(self, request) -> str:
        max_retries = 5
        retries = 0
        max_polls = 600
        polls = 0
        no_progress_polls = 0
        last_progress = 0.0
        while True:
            try:
                polls += 1
                if polls > max_polls:
                    raise RuntimeError("Upload timed out while waiting for YouTube resumable completion")
                status, response = request.next_chunk()
                if response:
                    if "id" in response:
                        return response["id"]
                    raise RuntimeError(f"Unexpected upload response: {response}")
                if status is not None:
                    progress = float(status.progress() or 0.0)
                    logger.info("YouTube upload progress: %.1f%%", progress * 100)
                    if progress <= last_progress:
                        no_progress_polls += 1
                    else:
                        no_progress_polls = 0
                        last_progress = progress
                else:
                    no_progress_polls += 1

                if no_progress_polls >= 120:
                    raise RuntimeError(
                        "Upload stalled: no progress from YouTube resumable API for too many polls"
                    )
            except HttpError as e:
                error_text = ""
                try:
                    error_text = e.content.decode("utf-8", errors="ignore")
                except Exception:
                    error_text = str(e)
                if e.resp.status in (500, 502, 503, 504) and retries < max_retries:
                    wait_s = 2 ** retries
                    retries += 1
                    logger.warning(
                        "Retriable YouTube upload error (status=%s, attempt=%s/%s): %s",
                        e.resp.status,
                        retries,
                        max_retries,
                        error_text[:500],
                    )
                    sleep(wait_s)
                    continue
                raise RuntimeError(
                    f"YouTube upload failed with status={e.resp.status}: {error_text[:800]}"
                ) from e
            except Exception as e:
                if retries < max_retries:
                    wait_s = 2 ** retries
                    retries += 1
                    logger.warning(
                        "Transient upload error (attempt=%s/%s): %s",
                        retries,
                        max_retries,
                        str(e)[:500],
                    )
                    sleep(wait_s)
                    continue
                raise RuntimeError(f"Upload failed after retries: {e}") from e

    def _build_request_body(self, seo: dict, privacy: str = "public") -> dict:
        return {
            "snippet": {
                "title": seo.get("title", "")[:100],
                "description": seo.get("description", ""),
                "tags": seo.get("tags", []),
                "categoryId": CATEGORY_ENTERTAINMENT,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            }
        }

    def get_channel_stats(self, api_key: str, channel_handle: str) -> dict:
        """Fetch public channel stats using a YouTube Data API key (no OAuth needed)."""
        import httpx
        handle = channel_handle.lstrip("@")
        url = (
            f"https://www.googleapis.com/youtube/v3/channels"
            f"?part=statistics,snippet&forHandle={handle}&key={api_key}"
        )
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            raise RuntimeError(f"No channel found for handle @{handle}")
        stats = items[0]["statistics"]
        snippet = items[0]["snippet"]
        return {
            "name": snippet.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
        }

    def _get_service(self, scopes: list[str] | None = None):
        creds = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=scopes or [YOUTUBE_UPLOAD_SCOPE],
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
