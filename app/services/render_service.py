import logging
import math
import random
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_W, TARGET_H = 1080, 1920
# ASS/SRT FontSize units: rendered_px = FontSize * video_height / PlayResY (384)
# SRT_FONT_SIZE=19 → 19*1920/384 = 95px actual height per line
SRT_FONT_SIZE = 19
# Pillow renders in actual pixels on the 1080×1920 canvas
PIL_FONT_SIZE = 90
# 2 words per caption chunk = faster, punchier reading feel
CAPTION_WORDS_PER_SEGMENT = 2

_BG_AUDIO_DIR = Path(__file__).parent.parent.parent / "background_audio"
_NICHE_MUSIC_FOLDER = {
    "horror": "Horror",
    "mystery": "Mystery",
    "paranormal": "Horror",
    "twist_endings": "Mystery",
    "psychological": "Horror",
    "supernatural": "Horror",
    "slasher": "Horror",
    "folk_horror": "Horror",
}

# (font_path, index) — prefer bold variants
_FONT_CANDIDATES = [
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),   # Helvetica Neue Bold
    ("/System/Library/Fonts/Helvetica.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
]

def _find_font() -> tuple[str, int] | None:
    for fc, idx in _FONT_CANDIDATES:
        if Path(fc).exists():
            return (fc, idx)
    return None

_SYSTEM_FONT = _find_font()

# Check once at module load whether the subtitles filter is available
def _has_subtitles_filter() -> bool:
    result = subprocess.run(
        ["ffmpeg", "-filters"],
        capture_output=True, text=True
    )
    return "subtitles" in result.stdout


_SUBTITLES_AVAILABLE = _has_subtitles_filter()


class RenderService:
    def __init__(self, output_dir: str = "/tmp/shorts_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, video_paths: list[str], audio_path: str, script: str, job_id: str, word_timings: list = None, niche: str = "", cta: str = "") -> str:
        """
        Full pipeline:
          1. Apply subtle tail reverb to narration audio for a haunting finish
          2. Merge/crop background video clips to 1080x1920 at audio duration
          3. Burn-in captions (SRT via libass if available, otherwise Pillow overlay)
          4. Normalize audio loudness to -16 LUFS, mix in background music with ducking
        Returns path to the final MP4.
        """
        output_path = self.output_dir / f"{job_id}.mp4"
        music_path = self._pick_background_music(niche)
        if music_path:
            logger.info(f"Background music: {Path(music_path).name}")
        with tempfile.TemporaryDirectory() as tmp:
            processed_audio = self._apply_tail_reverb(audio_path, tmp)
            merged_bg = self._merge_and_crop_videos(video_paths, processed_audio, tmp)
            captioned = self._add_captions(merged_bg, script, processed_audio, tmp, word_timings, cta=cta)
            self._normalize_audio(captioned, str(output_path), music_path=music_path)
        logger.info(f"Rendered: {output_path}")
        return str(output_path)

    def _pick_background_music(self, niche: str) -> str | None:
        folder_name = _NICHE_MUSIC_FOLDER.get(niche)
        if not folder_name:
            return None
        folder = _BG_AUDIO_DIR / folder_name
        if not folder.exists():
            logger.warning(f"Background audio folder not found: {folder}")
            return None
        files = list(folder.glob("*.mp3"))
        return str(random.choice(files)) if files else None

    # ------------------------------------------------------------------
    # Step 1: merge & crop to vertical 9:16
    # ------------------------------------------------------------------

    def _merge_and_crop_videos(self, video_paths: list[str], audio_path: str, tmp: str) -> str:
        audio_duration = self._get_duration(audio_path)
        out = Path(tmp) / "merged.mp4"

        # Scale 4% larger than target so Ken Burns crop has room to move
        W_LARGE = int(TARGET_W * 1.04)
        H_LARGE = int(TARGET_H * 1.04)
        DX = W_LARGE - TARGET_W  # horizontal overflow pixels
        DY = H_LARGE - TARGET_H  # vertical overflow pixels

        # Trim each source video to a random 5-7 s clip from a random start point
        trimmed = []
        for i, vp in enumerate(video_paths):
            try:
                src_dur = self._get_duration(vp)
            except Exception:
                src_dur = 30.0
            clip_dur = random.uniform(5, 7)
            clip_dur = min(clip_dur, src_dur)
            max_start = max(0.0, src_dur - clip_dur - 0.5)
            start = random.uniform(0, max_start) if max_start > 0 else 0.0
            t = Path(tmp) / f"clip_{i}.mp4"
            # Ken Burns: slow drift from far corner toward center over clip duration.
            # setpts=PTS-STARTPTS resets t=0 at each clip so the expression is correct.
            # Color grade: slight desaturation + contrast boost for cinematic horror look.
            vf = (
                f"scale={W_LARGE}:{H_LARGE}:force_original_aspect_ratio=increase,"
                f"crop={W_LARGE}:{H_LARGE},setsar=1,setpts=PTS-STARTPTS,"
                f"crop={TARGET_W}:{TARGET_H}:"
                f"x={DX}*max(0\\,1-t/{clip_dur:.3f}):y={DY}*max(0\\,1-t/{clip_dur:.3f}),"
                f"eq=saturation=0.72:contrast=1.08:brightness=-0.02"
            )
            cmd = [
                "ffmpeg", "-ss", f"{start:.2f}", "-i", vp,
                "-t", f"{clip_dur:.2f}",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-an", "-y", str(t)
            ]
            self._run(cmd)
            trimmed.append(str(t))

        # Loop the clip sequence until it covers the full audio duration
        total_clip_dur = sum(
            self._get_duration(c) for c in trimmed
        )
        loops = math.ceil(audio_duration / total_clip_dur) if total_clip_dur > 0 else 1
        clips_to_concat = trimmed * loops

        concat_list = Path(tmp) / "concat.txt"
        with open(concat_list, "w") as f:
            for cp in clips_to_concat:
                f.write(f"file '{cp}'\n")

        cmd = [
            "ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-t", str(audio_duration + 2.0),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-an", "-y", str(out)
        ]
        self._run(cmd)
        return str(out)

    # ------------------------------------------------------------------
    # Step 2: add captions
    # ------------------------------------------------------------------

    def _add_captions(self, video_path: str, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "") -> str:
        if _SUBTITLES_AVAILABLE:
            try:
                return self._add_captions_srt(video_path, script, audio_path, tmp, word_timings, cta=cta)
            except Exception as e:
                logger.warning(f"SRT captions failed ({e}), falling back to drawtext")
        try:
            return self._add_captions_drawtext(video_path, script, audio_path, tmp, word_timings, cta=cta)
        except Exception as e:
            logger.warning(f"drawtext captions failed ({e}), muxing without captions")
            return self._mux_audio_only(video_path, audio_path, tmp)

    # --- libass / SRT path (when subtitles filter is available) ---

    def _add_captions_srt(self, video_path: str, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "") -> str:
        out = Path(tmp) / "captioned.mp4"
        srt_path = self._generate_srt(script, audio_path, tmp, word_timings, cta=cta)
        escaped_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
        font_arg = f",FontName=Helvetica" if not _SYSTEM_FONT else ""
        cmd = [
            "ffmpeg", "-i", video_path, "-i", audio_path,
            "-vf", (
                f"subtitles={escaped_srt}:force_style="
                f"'FontSize={SRT_FONT_SIZE},Bold=1,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,Outline=3,Shadow=2,"
                f"ShadowColour=&H80000000,Alignment=2,MarginV=160{font_arg}'"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-y", str(out)
        ]
        self._run(cmd)
        return str(out)

    # --- Pillow PNG overlay path (no drawtext/subtitles filter needed) ---

    def _add_captions_drawtext(self, video_path: str, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "") -> str:
        from PIL import Image

        out = Path(tmp) / "captioned.mp4"
        caption_data = self._get_caption_segments(script, audio_path, word_timings, cta=cta)
        total_dur = self._get_duration(audio_path)
        font = self._load_caption_font()

        # Transparent base frame reused for gaps between captions
        transparent_path = Path(tmp) / "transparent.png"
        Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0)).save(str(transparent_path))

        # Render one PNG per caption
        caption_pngs: list[tuple[float, float, str]] = []
        for i, (start, end, text) in enumerate(caption_data):
            png_path = Path(tmp) / f"cap_{i:04d}.png"
            self._render_caption_frame(text, font, png_path)
            caption_pngs.append((start, end, str(png_path)))

        # Build concat list: transparent gaps + caption images + trailing gap
        concat_path = Path(tmp) / "cap_concat.txt"
        lines: list[str] = []
        prev_end = 0.0
        for start, end, png_path in caption_pngs:
            gap = start - prev_end
            if gap > 0.001:
                lines += [f"file '{transparent_path}'", f"duration {gap:.4f}"]
            lines += [f"file '{png_path}'", f"duration {end - start:.4f}"]
            prev_end = end
        remaining = total_dur - prev_end
        if remaining > 0.001:
            lines += [f"file '{transparent_path}'", f"duration {remaining:.4f}"]
        lines.append(f"file '{transparent_path}'")   # last entry needs no duration
        with open(concat_path, "w") as f:
            f.write("\n".join(lines))

        # Create a single alpha-channel caption video track
        caption_track = self._build_alpha_caption_track(concat_path, tmp)
        if caption_track:
            self._run([
                "ffmpeg", "-i", video_path, "-i", str(caption_track), "-i", audio_path,
                "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:eof_action=endall[vout]",
                "-map", "[vout]", "-map", "2:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-y", str(out),
            ])
        else:
            # Fallback: chain up to 20 overlay filters
            self._run_chained_overlays(video_path, audio_path, caption_pngs[:20], out)
        return str(out)

    def _render_caption_frame(self, text: str, font, path: Path) -> None:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        lines = self._wrap_words(text, max_chars=14, max_lines=2)
        line_h = PIL_FONT_SIZE + 10
        total_h = line_h * len(lines)
        y_anchor = int(TARGET_H * 0.72)
        y_start = max(90, y_anchor - (total_h // 2))

        # Measure all lines to find the widest for the background bar
        line_widths = []
        for ln in lines:
            try:
                bbox = draw.textbbox((0, 0), ln, font=font)
                line_widths.append(bbox[2] - bbox[0])
            except Exception:
                line_widths.append(len(ln) * (PIL_FONT_SIZE // 2))
        max_w = max(line_widths) if line_widths else TARGET_W // 2

        # Semi-transparent dark background bar for readability
        pad_x, pad_y = 20, 8
        bar_x0 = (TARGET_W - max_w) // 2 - pad_x
        bar_y0 = y_start - pad_y
        bar_x1 = (TARGET_W + max_w) // 2 + pad_x
        bar_y1 = y_start + total_h + pad_y
        overlay = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([(bar_x0, bar_y0), (bar_x1, bar_y1)], fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        for li, ln in enumerate(lines):
            try:
                bbox = draw.textbbox((0, 0), ln, font=font)
                text_w = bbox[2] - bbox[0]
            except Exception:
                text_w = len(ln) * (PIL_FONT_SIZE // 2)
            x = (TARGET_W - text_w) // 2
            y = y_start + li * line_h
            try:
                draw.text(
                    (x, y), ln, font=font,
                    fill=(255, 255, 255, 255),
                    stroke_width=3, stroke_fill=(0, 0, 0, 255),
                )
            except TypeError:
                for dx, dy in [(-3,-3),(3,-3),(-3,3),(3,3),(0,-3),(0,3),(-3,0),(3,0)]:
                    draw.text((x+dx, y+dy), ln, font=font, fill=(0, 0, 0, 255))
                draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        img.save(str(path))

    def _build_alpha_caption_track(self, concat_path: Path, tmp: str) -> Path | None:
        """Encode PNG concat list into an alpha-channel video. Tries ffv1 → qtrle → prores."""
        attempts = [
            (Path(tmp) / "cap_track.mkv",  ["-c:v", "ffv1",     "-pix_fmt", "rgba",         "-r", "30"]),
            (Path(tmp) / "cap_track.mov",  ["-c:v", "qtrle",    "-pix_fmt", "argb",         "-r", "30"]),
            (Path(tmp) / "cap_prores.mov", ["-c:v", "prores_ks","-profile:v","4444","-pix_fmt","yuva444p10le","-r","30"]),
        ]
        for track_path, codec_args in attempts:
            r = subprocess.run(
                ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_path),
                 *codec_args, "-y", str(track_path)],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                logger.info(f"Caption track encoded with {codec_args[1]}: {track_path.name}")
                return track_path
            logger.debug(f"Caption codec {codec_args[1]} failed: {r.stderr[-200:]}")
        return None

    def _run_chained_overlays(
        self, video_path: str, audio_path: str,
        caption_pngs: list[tuple[float, float, str]], out: Path,
    ) -> None:
        inputs = ["-i", video_path, "-i", audio_path]
        for _, _, png in caption_pngs:
            inputs += ["-i", png]
        n = len(caption_pngs)
        parts = []
        for i, (start, end, _) in enumerate(caption_pngs):
            in_v  = f"[v{i}]" if i > 0 else "[0:v]"
            out_v = f"[v{i+1}]" if i < n - 1 else "[vout]"
            img_in = f"[{i + 2}:v]"
            parts.append(
                f"{in_v}{img_in}overlay=0:0:format=auto"
                f":enable=between(t\\,{start:.3f}\\,{end:.3f}){out_v}"
            )
        fc = ";".join(parts) if parts else "[0:v]copy[vout]"
        self._run([
            "ffmpeg", *inputs,
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-y", str(out),
        ])

    def _load_caption_font(self):
        from PIL import ImageFont
        if _SYSTEM_FONT:
            font_path, font_idx = _SYSTEM_FONT
            try:
                return ImageFont.truetype(font_path, PIL_FONT_SIZE, index=font_idx)
            except Exception:
                pass
        return ImageFont.load_default(size=PIL_FONT_SIZE)

    @staticmethod
    def _wrap_words(text: str, max_chars: int = 18, max_lines: int = 2) -> list[str]:
        words = text.split()
        lines, line = [], []
        for w in words:
            if line and len(" ".join(line + [w])) > max_chars:
                lines.append(" ".join(line))
                line = [w]
                if len(lines) >= max_lines:
                    break
            else:
                line.append(w)
        if line and len(lines) < max_lines:
            lines.append(" ".join(line))
        return lines if lines else [text[:max_chars]]

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

    def _normalize_audio(self, input_path: str, output_path: str, music_path: str | None = None):
        if music_path:
            # Duck music during hook (first 5s), normal mid-story, swell at climax (after 40s)
            audio_filter = (
                "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[vo];"
                "[1:a]volume=volume='if(lt(t,5),0.04,if(gt(t,40),0.16,0.10))':eval=frame[music];"
                "[vo][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd = [
                "ffmpeg", "-i", input_path,
                "-stream_loop", "-1", "-i", music_path,
                "-filter_complex", audio_filter,
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-movflags", "+faststart",
                "-shortest", "-y", output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return
            logger.warning(f"Music mix failed ({result.stderr[-300:]}), falling back to no music")

        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-movflags", "+faststart",
            "-y", output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("loudnorm failed, copying without normalization")
            self._run([
                "ffmpeg", "-i", input_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-movflags", "+faststart",
                "-y", output_path
            ])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_tail_reverb(self, audio_path: str, tmp: str) -> str:
        """Apply a subtle atmospheric echo to the narration for a haunting feel."""
        try:
            out = Path(tmp) / "audio_reverb.mp3"
            r = subprocess.run(
                ["ffmpeg", "-i", audio_path,
                 "-af", "aecho=0.6:0.55:80:0.15",
                 "-c:a", "libmp3lame", "-b:a", "128k", "-y", str(out)],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                return str(out)
            logger.warning(f"Tail reverb failed: {r.stderr[-200:]}")
        except Exception as e:
            logger.warning(f"Tail reverb error: {e}")
        return audio_path

    def _generate_srt(self, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "") -> Path:
        srt_path = Path(tmp) / "captions.srt"
        captions = self._get_caption_segments(script, audio_path, word_timings, cta=cta)
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(captions):
                f.write(f"{i + 1}\n")
                f.write(f"{self._fmt_time(start)} --> {self._fmt_time(end)}\n")
                f.write(f"{text}\n\n")
        return srt_path

    def _get_caption_segments(self, script: str, audio_path: str, word_timings: list = None, cta: str = "") -> list:
        """Returns list of (start_sec, end_sec, text) caption groups — compact word chunks."""
        clean_script = script.replace('"', '').replace('"', '').replace('"', '')
        duration = self._get_duration(audio_path)

        if word_timings:
            chunks = self._align_words_to_caption_chunks(word_timings, clean_script)
            if chunks:
                # The script sent to TTS already includes the CTA appended at the end,
                # so word_timings cover every word (story + CTA) at the correct timestamps.
                # Just ensure the final chunk reaches the end of the audio.
                last_s, last_e, last_t = chunks[-1]
                chunks[-1] = (last_s, max(last_e, duration - 0.05), last_t)
                return chunks

        # Fallback: proportional segmentation (no word timings available).
        # The full script (story + CTA) is segmented proportionally so CTA appears naturally.
        words = clean_script.split()
        if not words:
            return [(0.0, duration, clean_script)]
        words_per_sec = max(len(words) / max(duration, 0.01), 0.5)
        segments = []
        i = 0
        while i < len(words):
            chunk_words = words[i:i + CAPTION_WORDS_PER_SEGMENT]
            start = i / words_per_sec
            end = min((i + len(chunk_words)) / words_per_sec, duration)
            segments.append((start, end, " ".join(chunk_words)))
            i += CAPTION_WORDS_PER_SEGMENT
        # Extend last segment to fill the full audio duration
        if segments:
            s, e, t = segments[-1]
            segments[-1] = (s, max(e, duration - 0.05), t)
        return segments

    @staticmethod
    def _align_words_to_caption_chunks(word_timings: list, script: str = "") -> list:
        """Map word boundary events into caption chunks, restoring punctuation from script."""
        timed = []
        for entry in word_timings:
            word = (entry.get("word") or "").strip()
            if not word:
                continue
            timed.append({
                "word": word,
                "offset": float(entry.get("offset", 0.0) or 0.0),
                "duration": float(entry.get("duration", 0.0) or 0.0),
            })

        # edge-tts strips trailing punctuation from word tokens; restore from script
        if script and timed:
            script_words = script.split()

            def bare(w: str) -> str:
                return re.sub(r"[^\w]", "", w.lower())

            matched = []
            si = 0
            for tw in timed:
                tw_bare = bare(tw["word"])
                found = False
                for j in range(si, min(si + 8, len(script_words))):
                    if bare(script_words[j]) == tw_bare:
                        matched.append({**tw, "word": script_words[j]})
                        si = j + 1
                        found = True
                        break
                if not found:
                    matched.append(tw)
            timed = matched

        captions = []
        i = 0
        while i < len(timed):
            chunk = timed[i:i + CAPTION_WORDS_PER_SEGMENT]
            if not chunk:
                break
            start = chunk[0]["offset"]
            end = chunk[-1]["offset"] + chunk[-1]["duration"]
            end = max(end, start + 0.3)  # guarantee minimum display time
            text = " ".join(w["word"] for w in chunk)
            captions.append((start, end, text))
            i += CAPTION_WORDS_PER_SEGMENT
        return captions

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
