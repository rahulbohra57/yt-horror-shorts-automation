import logging
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from time import sleep

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
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

    def _execute_upload(self, request) -> str:
        for attempt in range(5):
            try:
                status, response = request.next_chunk()
                if response:
                    return response["id"]
            except HttpError as e:
                if e.resp.status in (500, 502, 503, 504):
                    sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError("Upload failed after retries")

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

    def _get_service(self):
        creds = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=[YOUTUBE_UPLOAD_SCOPE],
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
