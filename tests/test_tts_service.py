import asyncio
import pytest
from pathlib import Path
from app.services.tts_service import TTSService

@pytest.fixture
def tts():
    return TTSService(output_dir="/tmp/test_tts")

def test_output_dir_created(tts):
    assert Path("/tmp/test_tts").exists()

def test_generate_creates_file():
    tts = TTSService(output_dir="/tmp/test_tts")
    script = "He opened the door and froze. Nobody believed what happened next."
    output_path = asyncio.run(tts.generate(script, voice="en-US-AriaNeural"))
    assert Path(output_path).exists()
    assert Path(output_path).stat().st_size > 1000

def test_fallback_to_gtts_on_bad_voice():
    tts = TTSService(output_dir="/tmp/test_tts")
    output_path = asyncio.run(tts.generate("Short test script.", voice="invalid-voice-xyz"))
    assert Path(output_path).exists()

def test_output_is_mp3(tts):
    output_path = asyncio.run(tts.generate("Test sentence.", voice="en-US-AriaNeural"))
    assert output_path.endswith(".mp3")

def test_caching_returns_same_path():
    tts = TTSService(output_dir="/tmp/test_tts")
    script = "Unique caching test script for tts service."
    path1 = asyncio.run(tts.generate(script, voice="en-US-AriaNeural"))
    path2 = asyncio.run(tts.generate(script, voice="en-US-AriaNeural"))
    assert path1 == path2
