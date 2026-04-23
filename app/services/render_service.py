import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_W, TARGET_H = 1080, 1920
FONT_SIZE = 56

# Check once at module load whether the subtitles filter is available
def _has_subtitles_filter() -> bool:
    result = subprocess.run(
        ["ffmpeg", "-filters"],
        capture_output=True, text=True
    )
    return " subtitles " in result.stdout or "\tsubtitles\t" in result.stdout or "subtitles" in result.stdout


_SUBTITLES_AVAILABLE = _has_subtitles_filter()


class RenderService:
    def __init__(self, output_dir: str = "/tmp/shorts_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, video_paths: list[str], audio_path: str, script: str, job_id: str) -> str:
        """
        Full pipeline:
          1. Merge/crop background video clips to 1080x1920 at audio duration
          2. Burn-in captions (SRT via libass if available, otherwise Pillow overlay)
          3. Normalize audio loudness to -16 LUFS
        Returns path to the final MP4.
        """
        output_path = self.output_dir / f"{job_id}.mp4"
        with tempfile.TemporaryDirectory() as tmp:
            merged_bg = self._merge_and_crop_videos(video_paths, audio_path, tmp)
            captioned = self._add_captions(merged_bg, script, audio_path, tmp)
            self._normalize_audio(captioned, str(output_path))
        logger.info(f"Rendered: {output_path}")
        return str(output_path)

    # ------------------------------------------------------------------
    # Step 1: merge & crop to vertical 9:16
    # ------------------------------------------------------------------

    def _merge_and_crop_videos(self, video_paths: list[str], audio_path: str, tmp: str) -> str:
        audio_duration = self._get_duration(audio_path)
        out = Path(tmp) / "merged.mp4"
        scale_crop = (
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1"
        )

        if len(video_paths) == 1:
            cmd = [
                "ffmpeg", "-stream_loop", "-1", "-i", video_paths[0],
                "-t", str(audio_duration),
                "-vf", scale_crop,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an", "-y", str(out)
            ]
        else:
            concat_list = Path(tmp) / "concat.txt"
            with open(concat_list, "w") as f:
                for vp in video_paths:
                    f.write(f"file '{vp}'\n")
            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-t", str(audio_duration),
                "-vf", scale_crop,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an", "-y", str(out)
            ]

        self._run(cmd)
        return str(out)

    # ------------------------------------------------------------------
    # Step 2: add captions
    # ------------------------------------------------------------------

    def _add_captions(self, video_path: str, script: str, audio_path: str, tmp: str) -> str:
        if _SUBTITLES_AVAILABLE:
            return self._add_captions_ffmpeg(video_path, script, audio_path, tmp)
        else:
            logger.info("subtitles filter not available — using Pillow caption overlay")
            return self._add_captions_pillow(video_path, script, audio_path, tmp)

    # --- FFmpeg/libass path ---

    def _add_captions_ffmpeg(self, video_path: str, script: str, audio_path: str, tmp: str) -> str:
        out = Path(tmp) / "captioned.mp4"
        srt_path = self._generate_srt(script, audio_path, tmp)
        escaped_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
        cmd = [
            "ffmpeg", "-i", video_path, "-i", audio_path,
            "-vf", (
                f"subtitles={escaped_srt}:force_style="
                f"'FontSize={FONT_SIZE},PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,Outline=3,Alignment=2,MarginV=80'"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-y", str(out)
        ]
        self._run(cmd)
        return str(out)

    # --- Pillow fallback path ---

    def _add_captions_pillow(self, video_path: str, script: str, audio_path: str, tmp: str) -> str:
        """
        Renders caption frames as a video using Pillow + FFmpeg overlay.
        Steps:
          a) Build a list of (start, end, text) from the script duration.
          b) Render an RGBA caption overlay video via Pillow → PNG sequence → FFmpeg.
          c) Overlay it on top of the background video, mux with audio.
        """
        try:
            return self._add_captions_pillow_impl(video_path, script, audio_path, tmp)
        except Exception as exc:
            logger.warning(f"Pillow caption overlay failed ({exc}), skipping captions")
            return self._mux_audio_only(video_path, audio_path, tmp)

    def _add_captions_pillow_impl(self, video_path: str, script: str, audio_path: str, tmp: str) -> str:
        from PIL import Image, ImageDraw, ImageFont
        import math

        duration = self._get_duration(audio_path)
        fps = 30
        total_frames = math.ceil(duration * fps)

        sentences = [s.strip() for s in script.split(".") if s.strip()]
        time_per = duration / max(len(sentences), 1)
        segments = []
        for i, sentence in enumerate(sentences):
            start = i * time_per
            end = min(start + time_per, duration)
            segments.append((start, end, sentence + "."))

        # Try to load a reasonable font; fall back to default
        font = None
        font_candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for fc in font_candidates:
            if Path(fc).exists():
                try:
                    font = ImageFont.truetype(fc, FONT_SIZE)
                    break
                except Exception:
                    pass
        if font is None:
            font = ImageFont.load_default()

        caption_dir = Path(tmp) / "caption_frames"
        caption_dir.mkdir()

        # Render PNG frames for caption overlay
        for frame_idx in range(total_frames):
            t = frame_idx / fps
            img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            text = ""
            for start, end, seg_text in segments:
                if start <= t < end:
                    text = seg_text
                    break

            if text:
                # Word-wrap to ~24 chars per line
                words = text.split()
                lines, line = [], []
                for w in words:
                    line.append(w)
                    if len(" ".join(line)) > 24:
                        lines.append(" ".join(line[:-1]))
                        line = [w]
                if line:
                    lines.append(" ".join(line))

                line_h = FONT_SIZE + 10
                block_h = line_h * len(lines)
                y_start = TARGET_H - 80 - block_h

                for li, ln in enumerate(lines):
                    # Measure text width
                    try:
                        bbox = draw.textbbox((0, 0), ln, font=font)
                        text_w = bbox[2] - bbox[0]
                    except Exception:
                        text_w = len(ln) * (FONT_SIZE // 2)
                    x = (TARGET_W - text_w) // 2
                    y = y_start + li * line_h

                    # Outline
                    for dx in [-3, -2, 0, 2, 3]:
                        for dy in [-3, -2, 0, 2, 3]:
                            draw.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 220))
                    # White fill
                    draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))

            frame_path = caption_dir / f"frame_{frame_idx:06d}.png"
            img.save(str(frame_path))

        # Encode caption PNGs to a video
        caption_video = Path(tmp) / "captions.mp4"
        cmd_enc = [
            "ffmpeg",
            "-framerate", str(fps),
            "-i", str(caption_dir / "frame_%06d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuva420p",
            "-y", str(caption_video)
        ]
        # Try yuva420p; if it fails, fall back to overlay via overlay filter on rgba
        result = subprocess.run(cmd_enc, capture_output=True, text=True)
        if result.returncode != 0:
            # Fallback: encode as rgba and use overlay
            cmd_enc[cmd_enc.index("yuva420p")] = "rgba"
            self._run(cmd_enc)

        # Overlay captions on background + mux audio
        out = Path(tmp) / "captioned.mp4"
        cmd_overlay = [
            "ffmpeg",
            "-i", video_path,
            "-i", str(caption_video),
            "-i", audio_path,
            "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-y", str(out)
        ]
        self._run(cmd_overlay)
        return str(out)

    def _mux_audio_only(self, video_path: str, audio_path: str, tmp: str) -> str:
        """Simple mux: video + audio, no captions."""
        out = Path(tmp) / "captioned.mp4"
        cmd = [
            "ffmpeg", "-i", video_path, "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-y", str(out)
        ]
        self._run(cmd)
        return str(out)

    # ------------------------------------------------------------------
    # Step 3: loudness normalisation
    # ------------------------------------------------------------------

    def _normalize_audio(self, input_path: str, output_path: str):
        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "copy",
            "-y", output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # loudnorm can fail on silence or near-silence (NaN measurements); copy without normalizing
            logger.warning("loudnorm failed, copying audio without normalization")
            self._run([
                "ffmpeg", "-i", input_path, "-c", "copy", "-y", output_path
            ])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _generate_srt(self, script: str, audio_path: str, tmp: str) -> Path:
        duration = self._get_duration(audio_path)
        sentences = [s.strip() for s in script.split(".") if s.strip()]
        srt_path = Path(tmp) / "captions.srt"
        time_per = duration / max(len(sentences), 1)

        with open(srt_path, "w", encoding="utf-8") as f:
            for i, sentence in enumerate(sentences):
                start = i * time_per
                end = min(start + time_per, duration)
                f.write(f"{i + 1}\n")
                f.write(f"{self._fmt_time(start)} --> {self._fmt_time(end)}\n")
                f.write(f"{sentence}.\n\n")
        return srt_path

    def _get_duration(self, path: str) -> float:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
        return float(result.stdout.strip())

    def _fmt_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    def _run(self, cmd: list):
        logger.debug(f"FFmpeg cmd: {' '.join(str(c) for c in cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg error:\n{result.stderr[-1000:]}")
