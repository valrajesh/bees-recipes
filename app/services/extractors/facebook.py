"""Facebook Post, Reel, and Watch recipe caption extractor."""

import asyncio
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


class FacebookExtractor(BaseExtractor):
    """Extractor for Facebook posts, reels, and video URLs."""

    FACEBOOK_REGEX = re.compile(
        r"(?:https?:\/\/)?(?:www\.|m\.|web\.)?(?:facebook\.com|fb\.watch|fb\.com)\/(?:[a-zA-Z0-9.\-_]+\/(?:posts|videos|reel|reels)\/|share\/(?:p|r|v)\/|watch\/?\?|groups\/[a-zA-Z0-9._-]+\/posts\/|permalink\.php\?|photo\.php\?|[a-zA-Z0-9._-]+)",
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
        return "facebook"

    def can_handle(self, url: str) -> bool:
        """Checks if the URL is a recognized Facebook URL."""
        return bool(
            "facebook.com" in url.lower()
            or "fb.watch" in url.lower()
            or "fb.com" in url.lower()
        )

    def _detect_firewall_block(self, response_text: str, status_code: int) -> bool:
        """Detects if an enterprise proxy/firewall blocked the outgoing request to Facebook."""
        if status_code in (403, 503) and ("Application Blocked" in response_text or "social-media-block" in response_text or "Access to this website is denied" in response_text):
            return True
        return False

    def _fetch_post_content(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetches post text content, title, and image URL from Facebook OpenGraph metadata or DOM."""
        last_error = None
        target_url = url

        for user_agent in self.CRAWLER_USER_AGENTS:
            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            try:
                try:
                    res = requests.get(
                        target_url,
                        headers=headers,
                        timeout=settings.REQUEST_TIMEOUT_SECONDS,
                        allow_redirects=True,
                        verify=settings.SSL_VERIFY,
                    )
                except requests.exceptions.SSLError:
                    res = requests.get(
                        target_url,
                        headers=headers,
                        timeout=settings.REQUEST_TIMEOUT_SECONDS,
                        allow_redirects=True,
                        verify=False,
                    )

                if self._detect_firewall_block(res.text, res.status_code):
                    raise RuntimeError(
                        "Facebook access was blocked by your local network proxy / corporate firewall "
                        "(Rule: social-media-block-apps). To extract from Facebook, ensure outbound network access "
                        "or run without corporate firewall proxy."
                    )

                if res.status_code == 200 and res.text:
                    soup = BeautifulSoup(res.text, "html.parser")
                    og_title = soup.find("meta", property="og:title")
                    og_desc = (
                        soup.find("meta", property="og:description")
                        or soup.find("meta", attrs={"name": "description"})
                    )
                    og_image = (
                        soup.find("meta", property="og:image")
                        or soup.find("meta", attrs={"name": "twitter:image"})
                    )

                    title_val = og_title["content"].strip() if og_title and og_title.get("content") else None
                    desc_val = og_desc["content"].strip() if og_desc and og_desc.get("content") else None
                    image_val = og_image["content"].strip() if og_image and og_image.get("content") else None

                    # If OpenGraph description is present and not just generic Facebook login text
                    if desc_val and not desc_val.lower().startswith("log into facebook") and not desc_val.lower().startswith("log in to facebook"):
                        logger.info(f"Successfully retrieved Facebook post metadata via {user_agent[:20]} (len: {len(desc_val)})")
                        return desc_val, title_val, image_val

                    # Fallback to page title or body text
                    if title_val and len(title_val) > 20 and not "log in" in title_val.lower():
                        return title_val, title_val, image_val

            except RuntimeError:
                raise
            except Exception as e:
                last_error = e
                logger.debug(f"Facebook fetch attempt failed with UA {user_agent[:20]}: {e}")

        if last_error:
            logger.warning(f"All Facebook fetch attempts failed: {last_error}")
        return None, None, None

    async def extract_recipe(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Extracts structured recipe from Facebook post, video, or reel."""
        logger.info(f"Processing Facebook URL: {url}")

        raw_text, post_title, image_url = await asyncio.to_thread(self._fetch_post_content, url)

        extraction_method = "llm"
        if not raw_text or not raw_text.strip():
            if post_title and post_title.strip() and "facebook" not in post_title.lower():
                logger.info(f"Facebook body text unavailable. Attempting title inferred extraction: '{post_title}'")
                raw_text = (
                    f"FACEBOOK POST TITLE: {post_title}\n"
                    f"(Note: Post text was inaccessible due to network/auth limits. If this title describes a cooking recipe/dish, "
                    f"infer standard authentic ingredients and instructions. If it is NOT a recipe, mark is_recipe=false.)"
                )
                extraction_method = "llm_title_inferred"
            else:
                raise RuntimeError(
                    f"Could not retrieve recipe content or title from Facebook URL ({url}). "
                    "The post might be private, deleted, restricted to logged-in users, or blocked by network firewall."
                )

        context_hint = f"Platform: Facebook Post/Reel | URL: {url}"
        if post_title:
            context_hint += f" | Title/Header: {post_title}"

        # Extract structured recipe via Azure OpenAI
        title_inference_text = None
        if post_title:
            title_inference_text = (
                f"FACEBOOK POST TITLE: {post_title}\n"
                f"(Note: Post text extraction did not produce usable ingredients or instructions. "
                f"If this title describes a cooking recipe or dish, infer standard authentic ingredients and instructions. "
                f"If it is NOT a recipe, mark is_recipe=false.)"
            )
        extracted, used_title_retry = await llm_service.extract_recipe_with_title_retry_async(
            raw_text=raw_text,
            platform_context=context_hint,
            title_inference_text=title_inference_text,
            title_platform_context=context_hint,
        )
        if used_title_retry:
            extraction_method = "llm_title_inferred"

        images = [image_url] if image_url else []

        recipe_detail = RecipeDetailModel(
            name=extracted.name or post_title or "Facebook Recipe",
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
            sourceType="facebook",
            extractionMethod=extraction_method,
        )

        return RecipeResponse(recipeDetail=recipe_detail)
