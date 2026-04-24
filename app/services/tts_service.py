import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from gtts import gTTS
import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-GuyNeural"
DEFAULT_RATE = "+50%"
EDGE_TTS_MAX_RETRIES = 3


class TTSService:
    def __init__(self, output_dir: str = "/tmp/tts_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, text: str, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> tuple[str, list]:
        """
        Generate TTS audio and return (audio_path, word_timings).
        word_timings: list of {"word": str, "offset": float, "duration": float} in seconds.
        """
        clean = self._clean_for_tts(text)
        cache_key = hashlib.sha256(f"{clean}{voice}{rate}".encode()).hexdigest()
        output_path = self.output_dir / f"{cache_key}.mp3"
        timing_path = self.output_dir / f"{cache_key}.json"

        if output_path.exists() and timing_path.exists():
            logger.info(f"TTS cache hit: {output_path}")
            with open(timing_path) as f:
                return str(output_path), json.load(f)

        word_timings: list = []
        edge_error = None
        for attempt in range(1, EDGE_TTS_MAX_RETRIES + 1):
            try:
                word_timings = await self._edge_tts(clean, voice, rate, output_path)
                with open(timing_path, "w") as f:
                    json.dump(word_timings, f)
                logger.info(f"edge-tts generated: {output_path} ({len(word_timings)} words)")
                edge_error = None
                break
            except Exception as e:
                edge_error = e
                output_path.unlink(missing_ok=True)
                timing_path.unlink(missing_ok=True)
                if attempt < EDGE_TTS_MAX_RETRIES:
                    logger.warning(f"edge-tts attempt {attempt}/{EDGE_TTS_MAX_RETRIES} failed ({e}), retrying")
                    await asyncio.sleep(attempt)

        if edge_error is not None:
            allow_fallback = os.getenv("ALLOW_GTTS_FALLBACK", "false").lower() in {"1", "true", "yes"}
            if not allow_fallback:
                raise RuntimeError(f"edge-tts failed after retries: {edge_error}") from edge_error
            logger.warning(f"edge-tts failed ({edge_error}), falling back to gTTS")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._gtts_fallback, clean, output_path)

        return str(output_path), word_timings

    async def _edge_tts(self, text: str, voice: str, rate: str, output_path: Path) -> list:
        """Generate audio + word timings via edge-tts streaming."""
        # edge-tts API varies by version; newer/older builds may not support `boundary` kwarg.
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        except TypeError:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
        audio_chunks: list[bytes] = []
        word_timings: list = []

        async for chunk in communicate.stream():
            chunk_type = str(chunk.get("type", "")).lower()
            if chunk_type == "audio":
                audio_chunks.append(chunk.get("data", b""))
            elif "wordboundary" in chunk_type or chunk_type == "word_boundary":
                word_timings.append({
                    "word": chunk.get("text") or chunk.get("word") or "",
                    "offset": (chunk.get("offset", 0) or 0) / 1e7,    # ticks → seconds
                    "duration": (chunk.get("duration", 0) or 0) / 1e7,
                })

        if not audio_chunks:
            raise RuntimeError("edge-tts produced no audio")

        with open(output_path, "wb") as f:
            for c in audio_chunks:
                f.write(c)

        if output_path.stat().st_size < 100:
            raise RuntimeError("edge-tts produced empty output")

        return word_timings

    def _gtts_fallback(self, text: str, output_path: Path):
        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(str(output_path))
        logger.info(f"gTTS fallback generated: {output_path}")

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        # Remove Unicode curly quotes — TTS reads them aloud as "quote"
        text = text.replace('“', '').replace('”', '')
        text = text.replace('‘', '').replace('’', '')
        # Replace em/en dash with comma-space for a natural pause
        text = text.replace('—', ', ').replace('–', ', ')
        text = re.sub(r'["""]+', '', text)
        return text.strip()
