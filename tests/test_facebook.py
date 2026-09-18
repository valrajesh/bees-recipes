"""Unit tests for Facebook extractor."""

import pytest
from app.services.extractors.facebook import FacebookExtractor


@pytest.fixture
def facebook_extractor():
    return FacebookExtractor()


def test_facebook_url_detection(facebook_extractor):
    valid_urls = [
        "https://www.facebook.com/share/p/1Jo1KShv2F/",
        "https://facebook.com/share/p/1Jo1KShv2F/",
        "https://www.facebook.com/reel/1234567890/",
        "https://www.facebook.com/watch/?v=1234567890",
        "https://fb.watch/abcd1234ef/",
        "https://www.facebook.com/ChefName/posts/1234567890",
    ]
    for url in valid_urls:
        assert facebook_extractor.can_handle(url) is True


def test_facebook_non_matching_urls(facebook_extractor):
    invalid_urls = [
        "https://www.youtube.com/watch?v=h8MHptcwKwk",
        "https://instagram.com/reel/C3abc123XYZ",
        "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/",
        "https://twitter.com/user/status/12345",
    ]
    for url in invalid_urls:
        assert facebook_extractor.can_handle(url) is False


def test_facebook_firewall_detection(facebook_extractor):
    block_html = "<html><title>Application Blocked</title><body>social-media-block-apps</body></html>"
    assert facebook_extractor._detect_firewall_block(block_html, 503) is True
    assert facebook_extractor._detect_firewall_block("Normal page", 200) is False
