"""Platform-specific extractor implementations."""

from app.services.extractors.base import BaseExtractor
from app.services.extractors.youtube import YouTubeExtractor
from app.services.extractors.instagram import InstagramExtractor
from app.services.extractors.facebook import FacebookExtractor
from app.services.extractors.tiktok import TikTokExtractor
from app.services.extractors.web import WebExtractor

__all__ = [
    "BaseExtractor",
    "YouTubeExtractor",
    "InstagramExtractor",
    "FacebookExtractor",
    "TikTokExtractor",
    "WebExtractor",
]
