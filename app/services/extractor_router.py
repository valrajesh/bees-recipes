"""Extractor Router coordinating multi-platform recipe extraction."""

from typing import List
from app.schemas.recipe import RecipeResponse, SupportedPlatformsResponse
from app.services.extractors.base import BaseExtractor
from app.services.extractors.youtube import YouTubeExtractor
from app.services.extractors.instagram import InstagramExtractor
from app.services.extractors.facebook import FacebookExtractor
from app.services.extractors.tiktok import TikTokExtractor
from app.services.extractors.web import WebExtractor
from app.utils.logger import logger


class ExtractorRouter:
    """Routes target URLs to the appropriate platform extractor."""

    def __init__(self):
        # Order matters: specific video/social extractors first, general web extractor last
        self._extractors: List[BaseExtractor] = [
            YouTubeExtractor(),
            InstagramExtractor(),
            FacebookExtractor(),
            TikTokExtractor(),
            WebExtractor(),
        ]

    def get_extractor(self, url: str) -> BaseExtractor:
        """Finds the first extractor capable of handling the specified URL."""
        for extractor in self._extractors:
            if extractor.can_handle(url):
                return extractor
        raise ValueError(f"No suitable extractor found for URL: {url}")

    async def route_and_extract(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Determines the appropriate extractor and performs the extraction."""
        extractor = self.get_extractor(url)
        logger.info(f"Routing URL '{url}' to extractor '{extractor.platform_name}'")
        return await extractor.extract_recipe(url=url, force_llm=force_llm)

    def get_supported_platforms(self) -> SupportedPlatformsResponse:
        """Returns metadata about all supported platforms and sample URLs."""
        return SupportedPlatformsResponse(
            platforms=[
                {
                    "name": "YouTube",
                    "identifier": "youtube",
                    "url_patterns": [
                        "youtube.com/watch?v=...",
                        "youtube.com/shorts/...",
                        "youtu.be/..."
                    ],
                    "extraction_pipeline": "Transcript extraction via youtube-transcript-api (or video description fallback) -> Azure OpenAI Structured Outputs",
                    "example_url": "https://www.youtube.com/shorts/h8MHptcwKwk"
                },
                {
                    "name": "Instagram",
                    "identifier": "instagram",
                    "url_patterns": [
                        "instagram.com/p/SHORTCODE/",
                        "instagram.com/reel/SHORTCODE/",
                        "instagram.com/reels/SHORTCODE/"
                    ],
                    "extraction_pipeline": "Caption & metadata extraction via social crawler/Instaloader -> Azure OpenAI Structured Outputs",
                    "example_url": "https://www.instagram.com/reel/C1234567890/"
                },
                {
                    "name": "Facebook",
                    "identifier": "facebook",
                    "url_patterns": [
                        "facebook.com/share/p/...",
                        "facebook.com/reel/...",
                        "facebook.com/watch/...",
                        "facebook.com/.../posts/...",
                        "fb.watch/..."
                    ],
                    "extraction_pipeline": "OpenGraph metadata & post text extraction -> Azure OpenAI Structured Outputs",
                    "example_url": "https://www.facebook.com/share/p/1Jo1KShv2F/"
                },
                {
                    "name": "TikTok",
                    "identifier": "tiktok",
                    "url_patterns": [
                        "tiktok.com/@user/video/...",
                        "tiktok.com/t/...",
                        "vm.tiktok.com/...",
                        "vt.tiktok.com/..."
                    ],
                    "extraction_pipeline": "Official oEmbed metadata + OpenGraph post caption extraction -> Azure OpenAI Structured Outputs",
                    "example_url": "https://www.tiktok.com/@feelgoodfoodie/video/7187123456789012345"
                },
                {
                    "name": "Standard Web Pages",
                    "identifier": "web",
                    "url_patterns": [
                        "https://* (all valid recipe blogs and culinary websites)"
                    ],
                    "extraction_pipeline": "Fast Path: Schema.org JSON-LD (recipe-scrapers) | Fallback: Intelligent HTML clean -> Azure OpenAI Structured Outputs",
                    "example_url": "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/"
                }
            ]
        )


# Global router singleton
extractor_router = ExtractorRouter()
