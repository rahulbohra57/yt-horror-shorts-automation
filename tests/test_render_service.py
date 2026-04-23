import pytest
import subprocess
from pathlib import Path
from app.services.render_service import RenderService


@pytest.fixture
def renderer():
    return RenderService(output_dir="/tmp/test_render")


def test_output_dir_created(renderer):
    assert Path("/tmp/test_render").exists()


def _make_test_video(path: str, duration: int = 3):
    subprocess.run([
        "ffmpeg", "-f", "lavfi", "-i", f"color=c=blue:size=1080x1920:rate=30",
        "-t", str(duration), "-c:v", "libx264", "-y", path
    ], check=True, capture_output=True)


def _make_test_audio(path: str, duration: int = 3):
    subprocess.run([
        "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(duration), "-q:a", "9", "-acodec", "libmp3lame", "-y", path
    ], check=True, capture_output=True)


def test_render_produces_file(tmp_path):
    renderer = RenderService(output_dir=str(tmp_path / "output"))
    test_video = str(tmp_path / "bg.mp4")
    test_audio = str(tmp_path / "audio.mp3")
    _make_test_video(test_video)
    _make_test_audio(test_audio)

    output = renderer.render(
        video_paths=[test_video],
        audio_path=test_audio,
        script="He opened the door and froze. Nobody believed her.",
        job_id="test_001"
    )
    assert Path(output).exists()
    assert Path(output).stat().st_size > 10000


def test_output_is_mp4(tmp_path):
    renderer = RenderService(output_dir=str(tmp_path / "output"))
    test_video = str(tmp_path / "bg.mp4")
    test_audio = str(tmp_path / "audio.mp3")
    _make_test_video(test_video, duration=2)
    _make_test_audio(test_audio, duration=2)

    output = renderer.render([test_video], test_audio, "Short test.", "test_002")
    assert output.endswith(".mp4")


def test_render_with_multiple_clips(tmp_path):
    renderer = RenderService(output_dir=str(tmp_path / "output"))
    video1 = str(tmp_path / "v1.mp4")
    video2 = str(tmp_path / "v2.mp4")
    test_audio = str(tmp_path / "audio.mp3")
    _make_test_video(video1, duration=2)
    _make_test_video(video2, duration=2)
    _make_test_audio(test_audio, duration=4)

    output = renderer.render([video1, video2], test_audio, "Two clips test.", "test_003")
    assert Path(output).exists()
