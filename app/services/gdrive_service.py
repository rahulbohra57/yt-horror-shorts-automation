import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GDriveService:
    def __init__(self, service_account_json: str, folder_id: str):
        self.folder_id = folder_id
        self._svc = self._build(service_account_json)

    def _build(self, service_account_json: str):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def upload(self, file_path: str, filename: str = None) -> str:
        """Upload MP4 to the configured Drive folder and return a public download URL."""
        from googleapiclient.http import MediaFileUpload

        path = Path(file_path)
        name = filename or path.name

        file_meta = {"name": name, "parents": [self.folder_id]}
        media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)

        file = (
            self._svc.files()
            .create(body=file_meta, media_body=media, fields="id")
            .execute()
        )
        file_id = file["id"]

        self._svc.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        url = f"https://drive.google.com/uc?id={file_id}&export=download"
        logger.info("GDrive upload complete: %s", url)
        return url
