"""Unit tests for Instagram extractor."""

import pytest
from app.services.extractors.instagram import InstagramExtractor


@pytest.fixture
def instagram_extractor():
    return InstagramExtractor()


def test_instagram_url_detection(instagram_extractor):
    valid_urls = [
        ("https://www.instagram.com/reel/C3abc123XYZ/", "C3abc123XYZ"),
        ("https://instagram.com/reel/C3abc123XYZ", "C3abc123XYZ"),
        ("https://www.instagram.com/p/B_123xyz987/", "B_123xyz987"),
        ("https://instagram.com/reels/C3abc123XYZ/", "C3abc123XYZ"),
        ("https://www.instagram.com/p/DN026BtRHoW/?stkn=MXg1YTRob3N2dXgxdQ==", "DN026BtRHoW"),
    ]
    for url, expected_code in valid_urls:
        assert instagram_extractor.can_handle(url) is True
        assert instagram_extractor.extract_shortcode(url) == expected_code


def test_instagram_non_matching_urls(instagram_extractor):
    invalid_urls = [
        "https://www.youtube.com/watch?v=h8MHptcwKwk",
        "https://tiktok.com/@user/video/12345",
        "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/",
    ]
    for url in invalid_urls:
        assert instagram_extractor.can_handle(url) is False
