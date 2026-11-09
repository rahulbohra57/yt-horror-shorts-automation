import json
import logging
import math
import random
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_W, TARGET_H = 1080, 1920
# Up to 2 words per caption chunk = faster, punchier reading feel
CAPTION_WORDS_PER_SEGMENT = 2

_BG_AUDIO_DIR = Path(__file__).parent.parent.parent / "background_audio"
_SUSPENSE_FOLDER = _BG_AUDIO_DIR / "suspense"
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Per-niche caption style, keyed to presets in templates/captions.json.
# High-energy niches get the bolder yellow treatment; the rest stay on the
# readable default white style.
_NICHE_CAPTION_STYLE = {
    "slasher": "bold_yellow",
    "supernatural": "bold_yellow",
    "folk_horror": "bold_yellow",
}

# Caption chunks containing any of these words are rendered in the accent
# color (regardless of the base style) to punch up the scariest beats.
_IMPACT_WORDS = {
    "dead", "death", "died", "kill", "killed", "killer", "blood", "scream",
    "screamed", "run", "help", "hide", "trapped", "watching", "behind",
    "gone", "missing", "afraid", "terrified", "horror", "ghost", "demon",
    "curse", "cursed", "monster", "attack", "danger", "bleeding", "silence",
}

_ACCENT_HEX = "#FFD232"                  # gold/amber, used in SRT <font color> tags
_ACCENT_COLOR_RGB = (255, 210, 50, 255)  # same color as Pillow RGBA
_BLOOD_RED = (235, 40, 40, 255)

_TEXT_MAX_WIDTH = 940
_HOOK_CARD_SECONDS = 2.0
_HOOK_CARD_FONT_SIZE = 132
_HOOK_CARD_Y = 330
_END_CARD_FONT_SIZE = 96
_END_CARD_Y = 620
_FORMAT_FONT_SIZE = 64
_FORMAT_MARGIN_X = 70
_FORMAT_Y = 190
_FADE_SECONDS = 0.35

# Shots shrink from the longest to the shortest length as the story nears its climax.
_SHOT_MAX_SECONDS = 4.5
_SHOT_MIN_SECONDS = 2.0
_BEAT_MIN_SECONDS = 0.8
_CLIMAX_PROGRESS = 0.7
_CAMERA_MOVES = ["push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down"]

# Near-lossless between steps, so only the single final encode costs quality.
_INTERMEDIATE_VIDEO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", "30", "-threads", "1"]
# The bitrate cap keeps a 60-second file under Cloudinary's 100 MB upload limit.
_FINAL_VIDEO = ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-r", "30", "-threads", "2"]

_DEFAULT_GRADE = "eq=saturation=0.6:contrast=1.16:gamma=0.86,colorbalance=bs=0.07:bm=0.03:rs=-0.04"
_NICHE_GRADES = {
    "horror": _DEFAULT_GRADE,
    "mystery": "eq=saturation=0.7:contrast=1.12:gamma=0.86,colorbalance=rs=0.05:gs=0.01:bs=-0.03:rh=0.04",
    "paranormal": "eq=saturation=0.45:contrast=1.14:gamma=0.86,colorbalance=gs=0.05:bs=0.05:rs=-0.05",
    "twist_endings": "eq=saturation=0.75:contrast=1.14:gamma=0.86,colorbalance=bs=0.04:rh=0.03",
    "psychological": "eq=saturation=0.5:contrast=1.2:gamma=0.86,colorbalance=gs=0.04:rs=-0.02:bs=-0.02",
    "supernatural": "eq=saturation=0.6:contrast=1.2:gamma=0.86,colorbalance=rs=0.08:bs=0.05:gs=-0.05",
    "slasher": "eq=saturation=0.8:contrast=1.22:gamma=0.86,colorbalance=rs=0.09:gs=-0.04:bs=-0.03",
    "folk_horror": "eq=saturation=0.62:contrast=1.1:gamma=0.86,colorbalance=rs=0.07:gs=0.03:bs=-0.08",
}

# A low boom plus a short burst of noise, played as the screen goes dark.
_STING_SOURCE = "aevalsrc=exprs='0.9*sin(2*PI*48*t)*exp(-2.2*t)+0.25*(random(0)*2-1)*exp(-7*t)':s=48000"


def _load_caption_styles() -> dict:
    try:
        with open(_TEMPLATES_DIR / "captions.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_CAPTION_STYLES = _load_caption_styles()
_DEFAULT_CAPTION_STYLE = {
    "font_size": 112, "color": "white", "outline_color": "black",
    "outline_width": 9, "alignment": 2, "margin_v": 470,
}

_ASS_COLOR_NAMES = {
    "white": "&H00FFFFFF", "black": "&H00000000", "yellow": "&H0000FFFF",
}
_PIL_COLOR_NAMES = {
    "white": (255, 255, 255, 255), "black": (0, 0, 0, 255), "yellow": (255, 220, 0, 255),
}

_BUNDLED_FONT = Path(__file__).parent.parent / "assets" / "fonts" / "Anton-Regular.ttf"

# (font_path, index), bundled first so output looks the same on every machine
_FONT_CANDIDATES = [
    (str(_BUNDLED_FONT), 0),
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
    return "subtitles" in result.stdout or "subtitles" in result.stderr


_SUBTITLES_AVAILABLE = _has_subtitles_filter()


class RenderService:
    def __init__(self, output_dir: str = "/tmp/shorts_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(
        self, video_paths: list[str], audio_path: str, script: str, job_id: str,
        word_timings: list = None, niche: str = "", cta: str = "",
        scenes: list[dict] = None, pacing: dict = None, hook_card: str = "",
        story_format: str = "", on_screen_text: str = "", end_card_text: str = "",
    ) -> str:
        """
        Full pipeline:
          1. Cut shots matched to story beats and join them at 1080x1920
          2. Add grain, the fade after the twist, and hook/format/end cards
          3. Burn in captions with the spoken word highlighted
          4. Normalize voice, mix music, add the post-twist sting
        Returns path to the final MP4.
        """
        output_path = self.output_dir / f"{job_id}.mp4"
        music_path = self._pick_background_music(niche)
        if music_path:
            logger.info(f"Background music: {Path(music_path).name}")
        with tempfile.TemporaryDirectory() as tmp:
            story_words = len(script.split()) - len(cta.split())
            merged_bg = self._merge_and_crop_videos(
                video_paths, audio_path, tmp, scenes=scenes, word_timings=word_timings,
                pacing=pacing, niche=niche, story_words=story_words,
            )
            composed = self._compose_overlays(
                merged_bg, audio_path, tmp, pacing=pacing, hook_card=hook_card,
                story_format=story_format, on_screen_text=on_screen_text, end_card_text=end_card_text,
            )
            captioned = self._add_captions(composed, script, audio_path, tmp, word_timings, cta=cta, niche=niche)
            self._normalize_audio(captioned, str(output_path), music_path=music_path, pacing=pacing)
        logger.info(f"Rendered: {output_path}")
        return str(output_path)

    def _pick_background_music(self, niche: str) -> str | None:
        if not _SUSPENSE_FOLDER.exists():
            logger.warning(f"Suspense audio folder not found: {_SUSPENSE_FOLDER}")
            return None
        files = list(_SUSPENSE_FOLDER.glob("*.mp3"))
        return str(random.choice(files)) if files else None

    # ------------------------------------------------------------------
    # Step 1: shots matched to the story, cut to vertical 9:16
    # ------------------------------------------------------------------

    def _merge_and_crop_videos(
        self, video_paths: list[str], audio_path: str, tmp: str, scenes: list[dict] = None,
        word_timings: list = None, pacing: dict = None, niche: str = "", story_words: int = 0,
    ) -> str:
        audio_duration = self._get_duration(audio_path)
        story_end = pacing["story_end"] if pacing else audio_duration
        beats = self._scene_beats(video_paths, scenes, word_timings, story_end, story_words)
        shots = self._build_shot_list(beats, story_end, audio_duration)
        grade = _NICHE_GRADES.get(niche, _DEFAULT_GRADE)

        cursors: dict[str, float] = {}
        durations: dict[str, float] = {}
        concat_list = Path(tmp) / "concat.txt"
        with open(concat_list, "w") as f:
            for i, (path, duration, move) in enumerate(shots):
                start = self._next_source_start(path, duration, cursors, durations)
                shot = Path(tmp) / f"shot_{i:03d}.mp4"
                self._cut_shot(path, start, duration, move, grade, shot)
                f.write(f"file '{shot}'\n")

        out = Path(tmp) / "merged.mp4"
        # All shots share encoder settings, so joining them costs no quality.
        self._run([
            "ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", "-an", "-y", str(out),
        ])
        return str(out)

    @staticmethod
    def _is_image(path: str) -> bool:
        return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}

    def _scene_beats(
        self, video_paths: list[str], scenes: list[dict] | None, word_timings: list | None,
        story_end: float, story_words: int,
    ) -> list[tuple[str, float, float]]:
        """Return (path, start, end) beats covering the narrated story."""
        starts: list[tuple[str, float]] = []
        for scene in scenes or []:
            index = int(scene.get("word_index", 0))
            if word_timings and index < len(word_timings):
                at = float(word_timings[index]["offset"])
            else:
                at = story_end * index / max(story_words, 1)
            starts.append((scene["path"], min(at, story_end)))

        if not starts:
            count = max(len(video_paths), math.ceil(story_end / _SHOT_MAX_SECONDS))
            step = story_end / count
            starts = [(video_paths[i % len(video_paths)], i * step) for i in range(count)]

        starts[0] = (starts[0][0], 0.0)
        beats = []
        for i, (path, at) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else story_end
            if end - at >= _BEAT_MIN_SECONDS or i == len(starts) - 1:
                beats.append((path, at, end))
            elif beats:
                beats[-1] = (beats[-1][0], beats[-1][1], end)
        return beats

    def _build_shot_list(
        self, beats: list[tuple[str, float, float]], story_end: float, audio_duration: float,
    ) -> list[tuple[str, float, str]]:
        """Split beats into shots that get shorter as the story approaches its climax."""
        shots: list[tuple[str, float, str]] = []
        last_move = ""
        for path, start, end in beats:
            at = start
            while end - at > 0.05:
                progress = min(at / max(story_end, 0.01), 1.0)
                longest = _SHOT_MAX_SECONDS - (_SHOT_MAX_SECONDS - _SHOT_MIN_SECONDS) * progress ** 1.5
                duration = min(longest, end - at)
                if end - at - duration < 1.0:
                    duration = end - at
                if progress >= _CLIMAX_PROGRESS:
                    move = "push_in"
                else:
                    move = random.choice([m for m in _CAMERA_MOVES if m != last_move])
                shots.append((path, duration, move))
                last_move = move
                at += duration
        tail = audio_duration + 0.5 - story_end
        if tail > 0.05:
            shots.append((beats[-1][0], tail, "static"))
        return shots

    def _next_source_start(
        self, path: str, duration: float, cursors: dict[str, float], durations: dict[str, float],
    ) -> float:
        """Walk forward through each source so repeat cuts show different frames."""
        if self._is_image(path):
            return 0.0
        if path not in durations:
            try:
                durations[path] = self._get_duration(path)
            except Exception:
                durations[path] = 30.0
        source = durations[path]
        room = max(0.0, source - duration - 0.5)
        if path not in cursors:
            cursors[path] = random.uniform(0, room * 0.25) if room > 0 else 0.0
        start = cursors[path] if cursors[path] <= room else 0.0
        cursors[path] = start + duration + 0.5
        return start

    @staticmethod
    def _camera_filter(move: str, duration: float) -> str:
        frames = max(int(math.ceil(duration * 30)), 1)
        progress = f"min(1,on/{frames})"
        center_x, center_y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
        pan_x, pan_y = "(iw-iw/zoom)", "(ih-ih/zoom)"
        z, x, y = {
            "push_in": (f"1.02+0.12*{progress}", center_x, center_y),
            "pull_out": (f"1.14-0.12*{progress}", center_x, center_y),
            "pan_right": ("1.1", f"{pan_x}*{progress}", center_y),
            "pan_left": ("1.1", f"{pan_x}*(1-{progress})", center_y),
            "tilt_down": ("1.1", center_x, f"{pan_y}*{progress}"),
            "tilt_up": ("1.1", center_x, f"{pan_y}*(1-{progress})"),
            "static": ("1.03", center_x, center_y),
        }[move]
        return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={TARGET_W}x{TARGET_H}:fps=30"

    def _cut_shot(self, path: str, start: float, duration: float, move: str, grade: str, out: Path) -> None:
        # Scaling up first gives the camera half-pixel steps, so slow moves stay smooth.
        vf = (
            f"fps=30,scale={TARGET_W * 2}:{TARGET_H * 2}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={TARGET_W * 2}:{TARGET_H * 2},setsar=1,"
            f"{self._camera_filter(move, duration)},setsar=1,{grade}"
        )
        if self._is_image(path):
            source = ["-loop", "1", "-framerate", "30", "-t", f"{duration + 0.3:.3f}", "-i", path]
        else:
            source = ["-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", path]
        self._run(["ffmpeg", *source, "-t", f"{duration:.3f}", "-vf", vf, *_INTERMEDIATE_VIDEO, "-an", "-y", str(out)])

    # ------------------------------------------------------------------
    # Step 2: film texture, fade after the twist, and on-screen cards
    # ------------------------------------------------------------------

    def _compose_overlays(
        self, video_path: str, audio_path: str, tmp: str, pacing: dict = None, hook_card: str = "",
        story_format: str = "", on_screen_text: str = "", end_card_text: str = "",
    ) -> str:
        try:
            total = self._get_duration(audio_path)
            story_end = pacing["story_end"] if pacing else total
            inputs: list[str] = ["-i", video_path]
            base = "vignette=angle=PI/4.4,noise=alls=4:allf=t"
            if pacing:
                base += f",fade=t=out:st={story_end:.3f}:d={_FADE_SECONDS}:color=black"
            graph = [f"[0:v]{base}[v0]"]
            layer = 0

            def add_layer(input_args: list[str], overlay_options: str) -> None:
                nonlocal layer
                inputs.extend(input_args)
                graph.append(f"[v{layer}][{layer + 1}:v]overlay=0:0:format=auto{overlay_options}[v{layer + 1}]")
                layer += 1

            track = self._build_format_track(story_format, on_screen_text, story_end, tmp)
            if track:
                add_layer(["-i", str(track)], f":eof_action=pass:enable='lt(t,{story_end:.3f})'")
            if hook_card:
                card = Path(tmp) / "hook_card.png"
                self._render_hook_card(hook_card, card)
                add_layer(["-i", str(card)], f":enable='lte(t,{_HOOK_CARD_SECONDS})'")
            if pacing and end_card_text:
                card = Path(tmp) / "end_card.png"
                self._render_end_card(end_card_text, card)
                add_layer(["-i", str(card)], f":enable='gte(t,{pacing['cta_start']:.3f})'")

            out = Path(tmp) / "composed.mp4"
            self._run([
                "ffmpeg", *inputs, "-filter_complex", ";".join(graph), "-map", f"[v{layer}]",
                "-t", f"{total + 0.2:.3f}", *_INTERMEDIATE_VIDEO, "-an", "-y", str(out),
            ])
            return str(out)
        except Exception as e:
            logger.warning(f"Overlay pass failed ({e}), rendering without it")
            return video_path

    def _load_font(self, size: int):
        from PIL import ImageFont
        if _SYSTEM_FONT:
            font_path, font_idx = _SYSTEM_FONT
            try:
                return ImageFont.truetype(font_path, size, index=font_idx)
            except Exception:
                pass
        return ImageFont.load_default(size=size)

    @staticmethod
    def _text_width(draw, text: str, font) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _wrap_to_width(self, draw, words: list[str], font, max_width: int) -> list[list[int]]:
        """Greedy wrap that returns word indices per line, and never drops a word."""
        lines: list[list[int]] = [[]]
        for i, word in enumerate(words):
            candidate = " ".join([words[j] for j in lines[-1]] + [word])
            if lines[-1] and self._text_width(draw, candidate, font) > max_width:
                lines.append([])
            lines[-1].append(i)
        return lines

    def _draw_centered_block(self, img, lines: list[str], font, line_height: int, y: int, fill=(255, 255, 255, 255), stroke: int = 8) -> int:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            x = (TARGET_W - self._text_width(draw, line, font)) // 2
            draw.text((x, y + i * line_height), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        return y + len(lines) * line_height

    def _render_hook_card(self, text: str, path: Path) -> None:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = self._load_font(_HOOK_CARD_FONT_SIZE)
        words = text.upper().split()
        lines = [" ".join(words[i] for i in line) for line in self._wrap_to_width(draw, words, font, _TEXT_MAX_WIDTH)]
        line_height = int(_HOOK_CARD_FONT_SIZE * 1.18)
        bottom = self._draw_centered_block(img, lines, font, line_height, _HOOK_CARD_Y)
        ImageDraw.Draw(img).rectangle(
            [(TARGET_W // 2 - 150, bottom + 22), (TARGET_W // 2 + 150, bottom + 34)], fill=_BLOOD_RED,
        )
        img.save(str(path))

    def _render_end_card(self, text: str, path: Path) -> None:
        from PIL import Image
        img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        font = self._load_font(_END_CARD_FONT_SIZE)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        self._draw_centered_block(img, lines, font, int(_END_CARD_FONT_SIZE * 1.25), _END_CARD_Y, stroke=0)
        img.save(str(path))

    def _build_format_track(self, story_format: str, on_screen_text: str, story_end: float, tmp: str) -> Path | None:
        """Overlay that matches how the story is told, such as a CCTV stamp or countdown."""
        if story_format not in {"real_time", "evidence", "countdown", "rule", "confession"}:
            return None
        from PIL import Image, ImageDraw

        seconds = max(int(math.ceil(story_end)), 1)
        font = self._load_font(_FORMAT_FONT_SIZE)
        base_clock = random.randint(2, 3) * 3600 + random.randint(0, 59) * 60

        def frame_text(second: int) -> str:
            if story_format == "countdown":
                remaining = max(seconds - second, 0)
                return f"{remaining // 60:02d}:{remaining % 60:02d}"
            clock = base_clock + second
            stamp = f"{clock // 3600:02d}:{clock // 60 % 60:02d}:{clock % 60:02d}"
            return f"CAM 04   {stamp}" if story_format == "evidence" else f"LIVE   {stamp}"

        if story_format in {"rule", "confession"}:
            label = "RECORDED CONFESSION" if story_format == "confession" else f"RULE: {on_screen_text or 'DO NOT LOOK'}"
            frames = [label.upper()]
        else:
            frames = [frame_text(second) for second in range(seconds)]

        entries: list[str] = []
        for i, text in enumerate(frames):
            png = Path(tmp) / f"format_{i:04d}.png"
            img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            x, y = _FORMAT_MARGIN_X, _FORMAT_Y
            if story_format == "evidence":
                draw.ellipse([(x, y + 16), (x + 40, y + 56)], fill=_BLOOD_RED)
                x += 62
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 235), stroke_width=4, stroke_fill=(0, 0, 0, 220))
            img.save(str(png))
            hold = 1.0 if len(frames) > 1 else story_end
            entries += [f"file '{png}'", f"duration {hold:.4f}"]
        entries.append(entries[-2])
        concat_path = Path(tmp) / "format_concat.txt"
        concat_path.write_text("\n".join(entries))
        return self._build_alpha_caption_track(concat_path, tmp, name="format_track")

    # ------------------------------------------------------------------
    # Step 3: add captions
    # ------------------------------------------------------------------

    def _style_for_niche(self, niche: str) -> dict:
        style_name = _NICHE_CAPTION_STYLE.get(niche, "default")
        return _CAPTION_STYLES.get(style_name) or _DEFAULT_CAPTION_STYLE

    def _add_captions(self, video_path: str, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "", niche: str = "") -> str:
        style = self._style_for_niche(niche)
        try:
            return self._add_captions_pillow(video_path, script, audio_path, tmp, word_timings, style=style)
        except Exception as e:
            logger.warning(f"Pillow captions failed ({e}), falling back to subtitles")
        if _SUBTITLES_AVAILABLE:
            try:
                return self._add_captions_srt(video_path, script, audio_path, tmp, word_timings, cta=cta, style=style)
            except Exception as e:
                logger.warning(f"SRT captions failed ({e}), muxing without captions")
        return self._mux_audio_only(video_path, audio_path, tmp)

    # --- libass / SRT path, used only if the Pillow track cannot be built ---

    def _add_captions_srt(self, video_path: str, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "", style: dict = None) -> str:
        style = style or _DEFAULT_CAPTION_STYLE
        out = Path(tmp) / "captioned.mp4"
        srt_path = self._generate_srt(script, audio_path, tmp, word_timings, cta=cta)
        escaped_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
        primary_color = _ASS_COLOR_NAMES.get(style["color"], "&H00FFFFFF")
        # FFmpeg lays out SRT on a 288-high canvas, so sizes here are scaled from 1920.
        scale = 288 / TARGET_H
        cmd = [
            "ffmpeg", "-i", video_path, "-i", audio_path,
            "-vf", (
                f"subtitles={escaped_srt}:force_style="
                f"'FontSize={round(style['font_size'] * scale)},Bold=1,PrimaryColour={primary_color},"
                f"OutlineColour=&H00000000,Outline=1,Shadow=1,"
                f"ShadowColour=&H80000000,Alignment={style['alignment']},MarginV={round(style['margin_v'] * scale)}'"
            ),
            *_FINAL_VIDEO,
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-y", str(out)
        ]
        self._run(cmd)
        return str(out)

    # --- Pillow PNG overlay path: the primary caption renderer ---

    def _add_captions_pillow(self, video_path: str, script: str, audio_path: str, tmp: str, word_timings: list = None, style: dict = None) -> str:
        from PIL import Image

        style = style or _DEFAULT_CAPTION_STYLE
        out = Path(tmp) / "captioned.mp4"
        frames = self._caption_frames(script, audio_path, word_timings)
        total_dur = self._get_duration(audio_path)
        font = self._load_font(style["font_size"])

        # Transparent base frame reused for gaps between captions
        transparent_path = Path(tmp) / "transparent.png"
        Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0)).save(str(transparent_path))

        concat_path = Path(tmp) / "cap_concat.txt"
        lines: list[str] = []
        prev_end = 0.0
        for i, (start, end, words, active) in enumerate(frames):
            png_path = Path(tmp) / f"cap_{i:04d}.png"
            self._render_caption_frame(words, active, font, png_path, style=style)
            gap = start - prev_end
            if gap > 0.001:
                lines += [f"file '{transparent_path}'", f"duration {gap:.4f}"]
            lines += [f"file '{png_path}'", f"duration {max(end - start, 0.034):.4f}"]
            prev_end = max(end, prev_end)
        remaining = total_dur - prev_end
        if remaining > 0.001:
            lines += [f"file '{transparent_path}'", f"duration {remaining:.4f}"]
        lines.append(f"file '{transparent_path}'")   # last entry needs no duration
        concat_path.write_text("\n".join(lines))

        caption_track = self._build_alpha_caption_track(concat_path, tmp)
        if not caption_track:
            raise RuntimeError("no encoder could produce an alpha caption track")
        self._run([
            "ffmpeg", "-i", video_path, "-i", str(caption_track), "-i", audio_path,
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:eof_action=pass[vout]",
            "-map", "[vout]", "-map", "2:a",
            *_FINAL_VIDEO,
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{total_dur:.3f}", "-y", str(out),
        ])
        return str(out)

    def _render_caption_frame(self, words: list[str], active: int | None, font, path: Path, style: dict = None) -> None:
        from PIL import Image, ImageDraw
        style = style or _DEFAULT_CAPTION_STYLE
        base_color = _PIL_COLOR_NAMES.get(style["color"], (255, 255, 255, 255))
        highlight = (255, 255, 255, 255) if style["color"] == "yellow" else _ACCENT_COLOR_RGB
        outline = _PIL_COLOR_NAMES.get(style["outline_color"], (0, 0, 0, 255))
        stroke = style["outline_width"]
        img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        display = [w.upper() for w in words]
        lines = self._wrap_to_width(draw, display, font, _TEXT_MAX_WIDTH)[:2]
        line_height = int(style["font_size"] * 1.2)
        block_height = line_height * len(lines)
        if style["alignment"] == 8:
            y_start = style["margin_v"]
        else:
            y_start = TARGET_H - style["margin_v"] - block_height
        space = self._text_width(draw, "N N", font) - self._text_width(draw, "NN", font)

        def color_for(i: int):
            has_impact = self._chunk_has_impact(words[i])
            if active is None:
                return _ACCENT_COLOR_RGB if has_impact else base_color
            if i != active:
                return base_color
            return _BLOOD_RED if has_impact else highlight

        for row, indices in enumerate(lines):
            widths = [self._text_width(draw, display[i], font) for i in indices]
            x = (TARGET_W - sum(widths) - space * (len(indices) - 1)) // 2
            y = y_start + row * line_height
            for i, width in zip(indices, widths):
                draw.text((x + 5, y + 8), display[i], font=font, fill=(0, 0, 0, 120), stroke_width=stroke, stroke_fill=(0, 0, 0, 120))
                draw.text((x, y), display[i], font=font, fill=color_for(i), stroke_width=stroke, stroke_fill=outline)
                x += width + space
        img.save(str(path))

    _ALPHA_PIX_FMTS = {"yuva420p", "rgba", "bgra", "argb", "abgr", "ya8"}

    def _build_alpha_caption_track(self, concat_path: Path, tmp: str, name: str = "cap_track") -> Path | None:
        """Encode a PNG concat list into an alpha-channel video.

        Some ffmpeg/libvpx builds accept `-pix_fmt yuva420p` for vp9 and exit 0
        while silently dropping the alpha plane (encoding opaque yuv420p instead).
        That turns the overlay into an opaque black frame covering the whole
        background video, so accepting on exit code alone isn't enough; the
        actual output pixel format must be verified to carry alpha.
        """
        attempts = [
            (Path(tmp) / f"{name}.mkv",  ["-c:v", "ffv1",       "-pix_fmt", "rgba",      "-r", "30", "-threads", "2"]),
            (Path(tmp) / f"{name}.mov",  ["-c:v", "qtrle",      "-pix_fmt", "argb",      "-r", "30"]),
            (Path(tmp) / f"{name}.webm", ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-r", "30", "-b:v", "0", "-crf", "30", "-threads", "1"]),
        ]
        for track_path, codec_args in attempts:
            r = subprocess.run(
                ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_path),
                 *codec_args, "-y", str(track_path)],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and self._output_has_alpha(track_path):
                logger.info(f"Caption track encoded with {codec_args[1]}: {track_path.name}")
                return track_path
            if r.returncode == 0:
                logger.warning(f"Caption codec {codec_args[1]} exited 0 but dropped alpha, trying next")
            else:
                logger.debug(f"Caption codec {codec_args[1]} failed: {r.stderr[-200:]}")
        return None

    @staticmethod
    def _output_has_alpha(path: Path) -> bool:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
        )
        pix_fmt = result.stdout.strip()
        return pix_fmt in RenderService._ALPHA_PIX_FMTS

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
    # Step 4: loudness normalisation and music
    # ------------------------------------------------------------------

    def _music_volume_expression(self, pacing: dict | None, duration: float) -> str:
        """Scale music to the actual narration so the swell lands whatever the length."""
        story_end = pacing["story_end"] if pacing else duration
        cta_start = pacing["cta_start"] if pacing else duration
        hook_end = min(4.0, story_end * 0.1)
        swell = story_end * 0.7
        return (
            f"if(lt(t,{hook_end:.3f}),0.04,if(lt(t,{swell:.3f}),0.10,"
            f"if(lt(t,{story_end:.3f}),0.16,if(lt(t,{cta_start:.3f}),0,0.05))))"
        )

    def _normalize_audio(self, input_path: str, output_path: str, music_path: str | None = None, pacing: dict | None = None):
        # The picture was finalized in the caption step; copying it avoids another encode.
        video_args = ["-c:v", "copy", "-movflags", "+faststart"]
        if music_path:
            duration = self._get_duration(input_path)
            volume = self._music_volume_expression(pacing, duration)
            inputs = ["-i", input_path, "-stream_loop", "-1", "-i", music_path]
            bed = f"[1:a]volume=volume='{volume}':eval=frame[bed];"
            if pacing:
                delay = int(pacing["story_end"] * 1000)
                inputs += ["-f", "lavfi", "-t", "3", "-i", _STING_SOURCE]
                bed = (
                    f"[1:a]volume=volume='{volume}':eval=frame[music];"
                    f"[2:a]lowpass=f=1800,adelay={delay}:all=1[sting];"
                    "[music][sting]amix=inputs=2:duration=first:normalize=0[bed];"
                )
            audio_filter = (
                "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[vo];" + bed +
                "[vo][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.84[aout]"
            )
            cmd = [
                "ffmpeg", *inputs,
                "-filter_complex", audio_filter,
                "-map", "0:v", "-map", "[aout]",
                *video_args,
                "-shortest", "-y", output_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return
            logger.warning(f"Music mix failed ({result.stderr[-300:].decode(errors='replace')}), falling back to no music")

        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            *video_args,
            "-y", output_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode != 0:
            logger.warning("loudnorm failed, copying without normalization")
            self._run(["ffmpeg", "-i", input_path, "-c", "copy", "-movflags", "+faststart", "-y", output_path])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _generate_srt(self, script: str, audio_path: str, tmp: str, word_timings: list = None, cta: str = "") -> Path:
        srt_path = Path(tmp) / "captions.srt"
        captions = self._get_caption_segments(script, audio_path, word_timings, cta=cta)
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(captions):
                display = f'<font color="{_ACCENT_HEX}">{text}</font>' if self._chunk_has_impact(text) else text
                f.write(f"{i + 1}\n")
                f.write(f"{self._fmt_time(start)} --> {self._fmt_time(end)}\n")
                f.write(f"{display}\n\n")
        return srt_path

    @staticmethod
    def _chunk_has_impact(text: str) -> bool:
        words = re.findall(r"[a-z']+", text.lower())
        return any(w in _IMPACT_WORDS for w in words)

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

    def _caption_frames(self, script: str, audio_path: str, word_timings: list = None) -> list:
        """(start, end, words, active_index) for each caption state; active is the spoken word."""
        clean_script = script.replace('"', '').replace('“', '').replace('”', '')
        duration = self._get_duration(audio_path)
        words = self._aligned_words(word_timings, clean_script) if word_timings else []
        if not words:
            return [
                (start, end, text.split(), None)
                for start, end, text in self._get_caption_segments(script, audio_path, None)
            ]

        chunks = self._group_caption_words(words)
        frames = []
        for c, chunk in enumerate(chunks):
            texts = [w["word"] for w in chunk]
            next_start = chunks[c + 1][0]["offset"] if c + 1 < len(chunks) else duration
            for i, w in enumerate(chunk):
                if i + 1 < len(chunk):
                    end = chunk[i + 1]["offset"]
                else:
                    end = max(w["offset"] + w["duration"], w["offset"] + 0.25)
                    if next_start - end < 0.25:
                        end = next_start
                    end = min(end, next_start)
                frames.append((w["offset"], end, texts, i))
        start, end, texts, active = frames[-1]
        frames[-1] = (start, max(end, duration - 0.05), texts, active)
        return frames

    @staticmethod
    def _group_caption_words(words: list[dict]) -> list[list[dict]]:
        """Group into short chunks that never run across a sentence ending."""
        chunks: list[list[dict]] = [[]]
        for w in words:
            chunks[-1].append(w)
            if len(chunks[-1]) >= CAPTION_WORDS_PER_SEGMENT or w["word"].rstrip("'\"”’")[-1:] in ".?!":
                chunks.append([])
        return [c for c in chunks if c]

    @staticmethod
    def _aligned_words(word_timings: list, script: str = "") -> list[dict]:
        """Clean word boundary events, restoring the punctuation edge-tts strips."""
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
        return timed

    @classmethod
    def _align_words_to_caption_chunks(cls, word_timings: list, script: str = "") -> list:
        """Map word boundary events into timed caption chunks."""
        captions = []
        for chunk in cls._group_caption_words(cls._aligned_words(word_timings, script)):
            start = chunk[0]["offset"]
            end = max(chunk[-1]["offset"] + chunk[-1]["duration"], start + 0.3)
            captions.append((start, end, " ".join(w["word"] for w in chunk)))
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
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg error:\n{result.stderr[-1000:].decode(errors='replace')}")
