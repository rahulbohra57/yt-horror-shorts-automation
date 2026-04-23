import pytest
from unittest.mock import patch, MagicMock
from app.services.youtube_service import YouTubeService


@pytest.fixture
def yt():
    return YouTubeService(client_id="test_id", client_secret="test_secret", refresh_token="test_token")


def test_build_metadata(yt):
    seo = {
        "title": "She Found a Locked Box After 20 Years #shorts",
        "description": "A mystery story.\n\nSubscribe for more.",
        "tags": ["#shorts", "#mystery", "#viral"]
    }
    body = yt._build_request_body(seo, privacy="public")
    assert body["snippet"]["title"] == seo["title"]
    assert body["snippet"]["categoryId"] == "22"
    assert body["status"]["privacyStatus"] == "public"
    assert "#shorts" in body["snippet"]["tags"]


def test_missing_credentials_raises():
    bad = YouTubeService(client_id="", client_secret="", refresh_token="")
    with pytest.raises(ValueError, match="credentials"):
        bad.upload("/tmp/fake.mp4", {})


def test_upload_calls_execute(yt):
    mock_service = MagicMock()
    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "abc123"})
    mock_service.videos.return_value.insert.return_value = mock_request

    with patch.object(yt, "_get_service", return_value=mock_service), \
         patch("os.path.getsize", return_value=1024), \
         patch("builtins.open", MagicMock()):
        result = yt.upload("/tmp/fake.mp4", {
            "title": "Test #shorts",
            "description": "Test desc",
            "tags": ["#shorts"]
        })
    assert result == "https://youtube.com/shorts/abc123"


def test_title_truncated_at_100_chars(yt):
    seo = {"title": "A" * 150, "description": "", "tags": []}
    body = yt._build_request_body(seo)
    assert len(body["snippet"]["title"]) <= 100
