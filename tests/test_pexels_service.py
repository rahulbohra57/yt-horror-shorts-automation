import pytest
from unittest.mock import patch, MagicMock
from app.services.pexels_service import PexelsService

@pytest.fixture
def service():
    return PexelsService(api_key="test_key", cache_dir="/tmp/test_pexels_cache")

def test_build_search_url(service):
    url = service._build_url("people walking", orientation="portrait")
    assert "people" in url
    assert "orientation=portrait" in url

def test_search_returns_list_on_mock(service):
    mock_response = {
        "videos": [
            {"id": 1, "video_files": [{"link": "https://example.com/v1.mp4", "width": 1080, "height": 1920, "quality": "hd"}]},
        ]
    }
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = MagicMock()
        results = service.search_videos("people walking", count=1)
    assert isinstance(results, list)
    assert len(results) == 1
    assert "url" in results[0]

def test_portrait_preferred_over_landscape(service):
    mock_response = {
        "videos": [
            {"id": 1, "video_files": [
                {"link": "https://example.com/portrait.mp4", "width": 1080, "height": 1920, "quality": "hd"},
                {"link": "https://example.com/landscape.mp4", "width": 1920, "height": 1080, "quality": "hd"},
            ]},
        ]
    }
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = MagicMock()
        results = service.search_videos("nature", count=1)
    assert "portrait" in results[0]["url"]

def test_empty_api_key_raises(service):
    bad_service = PexelsService(api_key="", cache_dir="/tmp/test")
    with pytest.raises(ValueError, match="PEXELS_API_KEY"):
        bad_service.search_videos("test")

def test_download_uses_cache(service, tmp_path):
    # Seed a fake cached file
    import hashlib
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    url = "https://example.com/video.mp4"
    cache_key = hashlib.md5(url.encode()).hexdigest()
    cached = cache_dir / f"{cache_key}.mp4"
    cached.write_bytes(b"fake_video_data")

    svc = PexelsService(api_key="test_key", cache_dir=str(cache_dir))
    result = svc.download_video(url)
    assert result == str(cached)
