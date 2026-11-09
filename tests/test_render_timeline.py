import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

from PIL import Image

from app.services.pexels_service import PexelsService
from app.services.render_service import RenderService
from app.services.tts_service import TTSService


def _renderer(tmp_path):
    return RenderService(output_dir=str(tmp_path))


def test_beats_follow_word_timings(tmp_path):
    timings = [{"word": f"w{i}", "offset": i * 0.5, "duration": 0.4} for i in range(40)]
    scenes = [{"path": "a.mp4", "word_index": 0}, {"path": "b.mp4", "word_index": 20}]
    beats = _renderer(tmp_path)._scene_beats(["a.mp4", "b.mp4"], scenes, timings, 20.0, 40)
    assert beats == [("a.mp4", 0.0, 10.0), ("b.mp4", 10.0, 20.0)]


def test_shots_cover_full_duration_and_quicken_near_the_end(tmp_path):
    renderer = _renderer(tmp_path)
    shots = renderer._build_shot_list([("a.mp4", 0.0, 40.0)], 40.0, 46.0)
    assert abs(sum(s[1] for s in shots) - 46.5) < 0.01
    body = shots[:-1]
    assert body[0][1] > body[-2][1]
    assert shots[-1][2] == "static"
    assert body[-2][2] == "push_in"


def test_camera_never_repeats_a_move_before_the_climax(tmp_path):
    shots = _renderer(tmp_path)._build_shot_list([("a.mp4", 0.0, 40.0)], 40.0, 40.0)
    early = [s[2] for s in shots if s[2] != "push_in"]
    assert all(a != b for a, b in zip(early, early[1:]))


def test_source_cursor_avoids_replaying_frames(tmp_path):
    renderer = _renderer(tmp_path)
    cursors, durations = {}, {"a.mp4": 60.0}
    first = renderer._next_source_start("a.mp4", 4.0, cursors, durations)
    second = renderer._next_source_start("a.mp4", 4.0, cursors, durations)
    assert second >= first + 4.0


def test_every_word_gets_its_own_highlight_state(tmp_path):
    renderer = _renderer(tmp_path)
    renderer._get_duration = lambda _: 3.0
    timings = [
        {"word": "Run", "offset": 0.0, "duration": 0.3},
        {"word": "now", "offset": 0.4, "duration": 0.3},
        {"word": "Please", "offset": 1.0, "duration": 0.3},
    ]
    frames = renderer._caption_frames("Run now. Please", "a.mp3", timings)
    assert [(f[2], f[3]) for f in frames] == [
        (["Run", "now."], 0), (["Run", "now."], 1), (["Please"], 0),
    ]
    assert frames[0][1] == 0.4


def test_captions_do_not_run_across_sentences():
    words = [{"word": w, "offset": 0.0, "duration": 0.1} for w in ["Your", "name.", "Your", "own", "name."]]
    chunks = RenderService._group_caption_words(words)
    assert [[w["word"] for w in c] for c in chunks] == [["Your", "name."], ["Your", "own"], ["name."]]


def test_music_cuts_out_during_the_pause(tmp_path):
    expression = _renderer(tmp_path)._music_volume_expression({"story_end": 40.0, "cta_start": 41.1}, 45.0)
    assert "lt(t,41.100),0,0.05" in expression
    assert "lt(t,28.000)" in expression


def test_long_caption_words_are_all_kept(tmp_path):
    from PIL import ImageDraw
    renderer = _renderer(tmp_path)
    draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    words = "SOMETHING EXTRAORDINARILY TERRIBLE HAPPENED".split()
    lines = renderer._wrap_to_width(draw, words, renderer._load_font(112), 940)
    assert sorted(i for line in lines for i in line) == [0, 1, 2, 3]


def test_generated_track_is_transparent_outside_text(tmp_path):
    renderer = _renderer(tmp_path)
    path = tmp_path / "card.png"
    renderer._render_hook_card("It Knows Your Name", path)
    image = Image.open(path)
    assert image.size == (1080, 1920)
    assert image.getpixel((5, 1900))[3] == 0


def _tone(path: Path, seconds: float):
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-ac", "1", "-ar", "24000",
         "-c:a", "libmp3lame", "-y", str(path)],
        check=True, capture_output=True,
    )


def test_pause_shifts_cta_timings(tmp_path):
    story, cta = tmp_path / "story.mp3", tmp_path / "cta.mp3"
    _tone(story, 4.0)
    _tone(cta, 2.0)
    tts = TTSService(output_dir=str(tmp_path / "tts"))
    tts.generate = AsyncMock(side_effect=[
        (str(story), [{"word": "end", "offset": 3.5, "duration": 0.4}]),
        (str(cta), [{"word": "follow", "offset": 0.1, "duration": 0.4}]),
    ])

    audio, timings, pacing = asyncio.run(tts.generate_with_pause("story", "cta", pause_seconds=1.0, tail_seconds=0.5))

    assert Path(audio).exists()
    assert abs(pacing["story_end"] - 3.9) < 0.01
    assert abs(timings[1]["offset"] - (pacing["cta_start"] + 0.1)) < 0.001
    assert abs(pacing["total"] - 7.5) < 0.25


def test_partial_timings_are_discarded(tmp_path):
    story, cta = tmp_path / "story.mp3", tmp_path / "cta.mp3"
    _tone(story, 1.0)
    _tone(cta, 1.0)
    tts = TTSService(output_dir=str(tmp_path / "tts"))
    tts.generate = AsyncMock(side_effect=[(str(story), [{"word": "a", "offset": 0, "duration": 0.2}]), (str(cta), [])])
    _, timings, _ = asyncio.run(tts.generate_with_pause("s", "c"))
    assert timings == []


def test_dark_clips_are_preferred(tmp_path, monkeypatch):
    service = PexelsService(api_key="k", cache_dir=str(tmp_path))
    levels = {"bright": 200.0, "dark": 40.0}
    monkeypatch.setattr(service, "_preview_brightness", lambda url: levels[url])
    ordered = service._prefer_dark([{"id": 1, "image": "bright"}, {"id": 2, "image": "dark"}])
    assert [c["id"] for c in ordered] == [2, 1]


def test_unknown_brightness_is_not_penalized(tmp_path, monkeypatch):
    service = PexelsService(api_key="k", cache_dir=str(tmp_path))
    monkeypatch.setattr(service, "_preview_brightness", lambda url: None)
    assert [c["id"] for c in service._prefer_dark([{"id": 1}, {"id": 2}])] == [1, 2]


def test_clips_too_dark_to_see_rank_below_usable_ones(tmp_path, monkeypatch):
    service = PexelsService(api_key="k", cache_dir=str(tmp_path))
    levels = {"black": 4.0, "night": 60.0}
    monkeypatch.setattr(service, "_preview_brightness", lambda url: levels[url])
    ordered = service._prefer_dark([{"id": 1, "image": "black"}, {"id": 2, "image": "night"}])
    assert [c["id"] for c in ordered] == [2, 1]


def test_still_image_cuts_into_a_vertical_shot(tmp_path):
    renderer = _renderer(tmp_path)
    still = tmp_path / "still.png"
    Image.new("RGB", (768, 1344), (40, 40, 60)).save(still)
    out = tmp_path / "shot.mp4"
    renderer._cut_shot(str(still), 0.0, 1.0, "push_in", "eq=saturation=0.6", out)
    assert out.exists()
    assert abs(renderer._get_duration(str(out)) - 1.0) < 0.1
