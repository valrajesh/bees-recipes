"""TikTok video and post recipe caption extractor."""

import asyncio
import json
import re
from typing import Optional, Tuple
import requests
from bs4 import BeautifulSoup
from app.config import settings
from app.schemas.recipe import (
    RecipeDetailModel,
    RecipeResponse,
)
from app.services.extractors.base import BaseExtractor
from app.services.llm_service import llm_service
from app.utils.logger import logger


class TikTokExtractor(BaseExtractor):
    """Extractor for TikTok video posts and share links."""

    TIKTOK_REGEX = re.compile(
        r"(?:https?:\/\/)?(?:www\.|vm\.|vt\.|m\.)?tiktok\.com\/(?:@[a-zA-Z0-9_.]+\/video\/(\d+)|t\/([a-zA-Z0-9]+)|([a-zA-Z0-9]+))",
        re.IGNORECASE
    )

    CRAWLER_USER_AGENTS = [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ]

    @property
    def platform_name(self) -> str:
        return "tiktok"

    def can_handle(self, url: str) -> bool:
        """Checks if the URL is a recognized TikTok URL."""
        return bool(
            "tiktok.com" in url.lower()
            or "vm.tiktok.com" in url.lower()
            or "vt.tiktok.com" in url.lower()
        )

    def _detect_firewall_block(self, response_text: str, status_code: int) -> bool:
        """Detects if an enterprise proxy/firewall blocked the outgoing request to TikTok."""
        if status_code in (403, 503) and (
            "Application Blocked" in response_text
            or "social-media-block" in response_text
            or "Access to this website is denied" in response_text
        ):
            return True
        return False

    def _fetch_via_oembed(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetches video title, author, and thumbnail image using TikTok's official public oEmbed endpoint."""
        try:
            oembed_url = f"https://www.tiktok.com/oembed?url={url}"
            headers = {"User-Agent": settings.DEFAULT_USER_AGENT}
            try:
                res = requests.get(
                    oembed_url,
                    headers=headers,
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                    verify=settings.SSL_VERIFY,
                )
            except requests.exceptions.SSLError:
                res = requests.get(
                    oembed_url,
                    headers=headers,
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                    verify=False,
                )

            if res.status_code == 200:
                data = res.json()
                title = data.get("title")  # On TikTok, 'title' contains the full caption
                author = data.get("author_name")
                thumbnail = data.get("thumbnail_url")
                if title and title.strip():
                    logger.info(f"Successfully retrieved TikTok caption via oEmbed (len: {len(title)})")
                    return title.strip(), author, thumbnail
        except Exception as e:
            logger.debug(f"TikTok oEmbed fetch failed: {e}")
        return None, None, None

    def _fetch_via_meta_crawler(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Scrapes OpenGraph/meta tag description and image for the TikTok video."""
        for ua in self.CRAWLER_USER_AGENTS:
            headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            try:
                try:
                    res = requests.get(
                        url,
                        headers=headers,
                        timeout=settings.REQUEST_TIMEOUT_SECONDS,
                        allow_redirects=True,
                        verify=settings.SSL_VERIFY,
                    )
                except requests.exceptions.SSLError:
                    res = requests.get(
                        url,
                        headers=headers,
                        timeout=settings.REQUEST_TIMEOUT_SECONDS,
                        allow_redirects=True,
                        verify=False,
                    )

                if self._detect_firewall_block(res.text, res.status_code):
                    raise RuntimeError(
                        "TikTok access was blocked by your local network proxy / corporate firewall "
                        "(Rule: social-media-block-apps). To extract from TikTok, ensure outbound network access "
                        "or run without corporate firewall restrictions."
                    )

                if res.status_code == 200 and res.text:
                    soup = BeautifulSoup(res.text, "html.parser")
                    og_desc = (
                        soup.find("meta", property="og:description")
                        or soup.find("meta", attrs={"name": "description"})
                    )
                    og_title = soup.find("meta", property="og:title")
                    og_image = (
                        soup.find("meta", property="og:image")
                        or soup.find("meta", attrs={"name": "twitter:image"})
                    )

                    desc_val = og_desc["content"].strip() if og_desc and og_desc.get("content") else None
                    title_val = og_title["content"].strip() if og_title and og_title.get("content") else None
                    image_val = og_image["content"].strip() if og_image and og_image.get("content") else None

                    if desc_val and not desc_val.lower().startswith("watch the latest video"):
                        logger.info(f"Successfully retrieved TikTok caption via crawler metadata (len: {len(desc_val)})")
                        return desc_val, title_val, image_val
            except RuntimeError:
                raise
            except Exception as e:
                logger.debug(f"TikTok meta crawler attempt failed with UA {ua[:20]}: {e}")

        return None, None, None

    async def extract_recipe(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Extracts structured recipe from TikTok video caption and metadata."""
        logger.info(f"Processing TikTok URL: {url}")

        # 1. Try public oEmbed endpoint
        caption, author, image_url = await asyncio.to_thread(self._fetch_via_oembed, url)

        # 2. Fallback to OpenGraph / Meta crawling
        if not caption:
            caption, author, image_url = await asyncio.to_thread(self._fetch_via_meta_crawler, url)

        extraction_method = "llm"
        if not caption or not caption.strip():
            if author or url:
                logger.info(f"TikTok caption unavailable. Attempting creator/URL inferred extraction for {url}")
                caption = (
                    f"TIKTOK VIDEO CREATOR: @{author or 'unknown'} | URL: {url}\n"
                    f"(Note: Video caption was inaccessible due to network/auth restrictions. If this video represents a culinary recipe/dish, "
                    f"infer standard authentic ingredients and instructions. If it is NOT a recipe, mark is_recipe=false.)"
                )
                extraction_method = "llm_title_inferred"
            else:
                raise RuntimeError(
                    f"Could not retrieve recipe content or metadata from TikTok URL ({url}). "
                    "The video might be private, deleted, restricted, or blocked by network firewall."
                )

        context_hint = f"Platform: TikTok Video | URL: {url}"
        if author:
            context_hint += f" | Creator: {author}"

        # Extract structured recipe via Azure OpenAI
        extracted = await llm_service.extract_recipe_structured_async(
            raw_text=caption,
            platform_context=context_hint
        )

        images = [image_url] if image_url else []

        recipe_detail = RecipeDetailModel(
            name=extracted.name,
            images=images,
            course=extracted.course or "Dinner",
            duration=extracted.duration or 30,
            storeType=extracted.storeType or "Colruyt",
            numberOfServings=extracted.numberOfServings or 4,
            nutriScore=extracted.nutriScore or "B",
            nutriScoreUrl="https://www.colruytgroup.com/nl/bewust-consumeren/nutri-score",
            tips=extracted.tips,
            nutritions=extracted.nutritions,
            instructions=extracted.instructions,
            ingredients=extracted.ingredients,
            sourceUrl=url,
            sourceType="tiktok",
            extractionMethod=extraction_method,
        )

        return RecipeResponse(recipeDetail=recipe_detail)
