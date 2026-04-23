import asyncio
import hashlib
import logging
from pathlib import Path
from gtts import gTTS
import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-AriaNeural"


class TTSService:
    def __init__(self, output_dir: str = "/tmp/tts_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, text: str, voice: str = DEFAULT_VOICE) -> str:
        """
        Generate TTS audio for the given text using edge-tts with gTTS fallback.

        Args:
            text: The script text to synthesize.
            voice: A valid edge-tts voice name (e.g. "en-US-AriaNeural").

        Returns:
            Absolute path to the generated MP3 file.
        """
        cache_key = hashlib.sha256(f"{text}{voice}".encode()).hexdigest()
        output_path = self.output_dir / f"{cache_key}.mp3"

        if output_path.exists():
            logger.info(f"TTS cache hit: {output_path}")
            return str(output_path)

        try:
            await self._edge_tts(text, voice, output_path)
            logger.info(f"edge-tts generated: {output_path}")
        except Exception as e:
            logger.warning(f"edge-tts failed ({e}), falling back to gTTS")
            output_path.unlink(missing_ok=True)  # remove empty/partial file
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._gtts_fallback, text, output_path)

        return str(output_path)

    async def _edge_tts(self, text: str, voice: str, output_path: Path):
        """Generate audio via Microsoft Edge TTS (free, no API key required)."""
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
        if not output_path.exists() or output_path.stat().st_size < 100:
            raise RuntimeError("edge-tts produced empty output")

    def _gtts_fallback(self, text: str, output_path: Path):
        """Generate audio via Google Translate TTS (free fallback, no API key required)."""
        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(str(output_path))
        logger.info(f"gTTS fallback generated: {output_path}")
