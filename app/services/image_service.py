"""Optional AI stills for moments stock footage cannot show. Failures are never fatal."""
import base64
import hashlib
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_STYLE = (
    "Dark cinematic horror film still, vertical 9:16, low key lighting, heavy shadows. "
    "No text, no captions, no watermark, no recognizable real people. Scene: "
)


class ImageService:
    def __init__(self, api_key: str, model: str, output_dir: str):
        self.api_key = api_key
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_still(self, prompt: str) -> str | None:
        if not self.api_key or not (prompt or "").strip():
            return None
        output = self.output_dir / f"{hashlib.sha256(prompt.encode()).hexdigest()}.png"
        if output.exists():
            return str(output)
        try:
            resp = requests.post(
                _API_URL.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json={
                    "contents": [{"parts": [{"text": _STYLE + prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": "9:16"},
                    },
                },
                timeout=120,
            )
            resp.raise_for_status()
            for candidate in resp.json().get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    data = part.get("inlineData", {}).get("data")
                    if data:
                        output.write_bytes(base64.b64decode(data))
                        return str(output)
            logger.warning("AI still response contained no image")
        except Exception as e:
            logger.warning(f"AI still generation failed (non-fatal): {str(e)[:200]}")
        return None
