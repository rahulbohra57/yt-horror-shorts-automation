import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from gtts import gTTS
import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-GB-RyanNeural"
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

    async def generate_with_pause(
        self, story: str, cta: str, pause_seconds: float = 1.1, tail_seconds: float = 0.5,
        voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE,
    ) -> tuple[str, list, dict]:
        """Narrate story and CTA separately with silence between, so the twist can land.

        Returns (audio_path, word_timings, pacing). Pacing marks where the story
        ends and the CTA starts on the combined timeline.
        """
        story_path, story_timings = await self.generate(story, voice=voice, rate=rate)
        cta_path, cta_timings = await self.generate(cta, voice=voice, rate=rate)

        story_duration = self._probe_duration(story_path)
        cta_start = story_duration + pause_seconds
        key = hashlib.sha256(f"{story_path}{cta_path}{pause_seconds}{tail_seconds}".encode()).hexdigest()
        combined = self.output_dir / f"{key}_paced.mp3"
        if not combined.exists():
            self._join_with_silence(story_path, cta_path, pause_seconds, tail_seconds, combined)

        # Both halves need timings; a partial set would misalign every caption.
        timings: list = []
        if story_timings and cta_timings:
            shifted = [{**t, "offset": t["offset"] + cta_start} for t in cta_timings]
            timings = story_timings + shifted
        story_end = story_duration
        if story_timings:
            last = story_timings[-1]
            story_end = min(story_duration, last["offset"] + last["duration"])
        pacing = {"story_end": story_end, "cta_start": cta_start, "total": self._probe_duration(str(combined))}
        return str(combined), timings, pacing

    @staticmethod
    def _probe_duration(path: str) -> float:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())

    @staticmethod
    def _join_with_silence(story: str, cta: str, pause: float, tail: float, output: Path) -> None:
        graph = (
            "[0:a]aformat=sample_rates=24000:channel_layouts=mono[a0];"
            "[2:a]aformat=sample_rates=24000:channel_layouts=mono[a2];"
            "[a0][1:a][a2][3:a]concat=n=4:v=0:a=1[out]"
        )
        silence = "anullsrc=r=24000:cl=mono"
        subprocess.run(
            ["ffmpeg", "-i", story, "-f", "lavfi", "-t", f"{pause:.3f}", "-i", silence,
             "-i", cta, "-f", "lavfi", "-t", f"{tail:.3f}", "-i", silence,
             "-filter_complex", graph, "-map", "[out]",
             "-c:a", "libmp3lame", "-q:a", "2", "-y", str(output)],
            capture_output=True, check=True,
        )

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
