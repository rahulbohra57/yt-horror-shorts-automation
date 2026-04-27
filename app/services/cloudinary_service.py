import logging
from pathlib import Path

import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)


class CloudinaryService:
    def __init__(self, cloud_name: str, api_key: str, api_secret: str):
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )

    def upload(self, file_path: str, public_id: str = None) -> str:
        """Upload MP4 to Cloudinary and return a direct CDN URL."""
        path = Path(file_path)
        kwargs = {
            "resource_type": "video",
            "folder": "horror_shorts",
            "overwrite": True,
        }
        if public_id:
            kwargs["public_id"] = public_id

        result = cloudinary.uploader.upload(str(path), **kwargs)
        url = result["secure_url"]
        logger.info("Cloudinary upload complete: %s", url)
        return url
