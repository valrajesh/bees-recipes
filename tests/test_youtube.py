"""Unit tests for YouTube extractor."""

import pytest
from app.services.extractors.youtube import YouTubeExtractor


@pytest.fixture
def youtube_extractor():
    return YouTubeExtractor()


def test_youtube_url_detection(youtube_extractor):
    valid_urls = [
        "https://www.youtube.com/watch?v=h8MHptcwKwk",
        "https://youtube.com/watch?v=h8MHptcwKwk&t=10s",
        "https://youtu.be/h8MHptcwKwk",
        "https://www.youtube.com/shorts/h8MHptcwKwk",
        "https://youtube.com/shorts/h8MHptcwKwk",
        "https://www.youtube.com/embed/h8MHptcwKwk",
    ]
    for url in valid_urls:
        assert youtube_extractor.can_handle(url) is True
        assert youtube_extractor.extract_video_id(url) == "h8MHptcwKwk"


def test_youtube_non_matching_urls(youtube_extractor):
    invalid_urls = [
        "https://instagram.com/reel/C12345/",
        "https://example.com/recipe",
        "https://vimeo.com/12345678",
    ]
    for url in invalid_urls:
        assert youtube_extractor.can_handle(url) is False
