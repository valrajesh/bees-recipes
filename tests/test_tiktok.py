"""Unit tests for TikTok extractor."""

import pytest
from app.services.extractors.tiktok import TikTokExtractor


@pytest.fixture
def tiktok_extractor():
    return TikTokExtractor()


def test_tiktok_url_detection(tiktok_extractor):
    valid_urls = [
        "https://www.tiktok.com/@feelgoodfoodie/video/7187123456789012345",
        "https://tiktok.com/@user_name/video/7187123456789012345?is_from_webapp=1",
        "https://www.tiktok.com/t/ZT8y7abcD/",
        "https://vm.tiktok.com/ZS2abcXYZ/",
        "https://vt.tiktok.com/ZS2abcXYZ/",
    ]
    for url in valid_urls:
        assert tiktok_extractor.can_handle(url) is True


def test_tiktok_non_matching_urls(tiktok_extractor):
    invalid_urls = [
        "https://www.youtube.com/watch?v=h8MHptcwKwk",
        "https://instagram.com/reel/C3abc123XYZ",
        "https://facebook.com/share/p/1Jo1KShv2F/",
        "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/",
    ]
    for url in invalid_urls:
        assert tiktok_extractor.can_handle(url) is False


def test_tiktok_firewall_detection(tiktok_extractor):
    block_html = "<html><title>Application Blocked</title><body>social-media-block-apps</body></html>"
    assert tiktok_extractor._detect_firewall_block(block_html, 503) is True
    assert tiktok_extractor._detect_firewall_block("Normal page", 200) is False
