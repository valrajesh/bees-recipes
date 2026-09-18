"""Instagram Post and Reel recipe caption extractor."""

import asyncio
import re
from typing import Optional, Tuple
import requests
from bs4 import BeautifulSoup
import instaloader
import instaloader.exceptions as iexceptions
from app.config import settings
from app.schemas.recipe import (
    RecipeDetailModel,
    RecipeResponse,
)
from app.services.extractors.base import BaseExtractor
from app.services.llm_service import llm_service
from app.utils.logger import logger


class InstagramExtractor(BaseExtractor):
    """Extractor for Instagram posts and reels."""

    INSTAGRAM_REGEX = re.compile(
        r"(?:https?:\/\/)?(?:www\.)?instagram\.com\/(?:p|reel|reels)\/([a-zA-Z0-9_-]+)",
        re.IGNORECASE
    )

    # Social crawler user-agents that Instagram reliably serves full OpenGraph captions to
    CRAWLER_USER_AGENTS = [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    ]

    def __init__(self):
        self._loader: Optional[instaloader.Instaloader] = None

    @property
    def platform_name(self) -> str:
        return "instagram"

    def can_handle(self, url: str) -> bool:
        """Checks if the URL is an Instagram post or reel."""
        return bool(self.INSTAGRAM_REGEX.search(url))

    def extract_shortcode(self, url: str) -> Optional[str]:
        """Extracts the Instagram shortcode from the URL."""
        match = self.INSTAGRAM_REGEX.search(url)
        return match.group(1) if match else None

    def _get_loader(self) -> instaloader.Instaloader:
        """Initializes and configures the Instaloader instance."""
        if self._loader is None:
            loader = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                quiet=True,
                user_agent=settings.DEFAULT_USER_AGENT,
            )

            # Ensure SSL setting is respected
            try:
                loader.context._session.verify = settings.SSL_VERIFY
            except Exception:
                pass

            # Optional authentication if credentials provided
            if settings.INSTAGRAM_USERNAME and settings.INSTAGRAM_PASSWORD:
                try:
                    loader.login(settings.INSTAGRAM_USERNAME, settings.INSTAGRAM_PASSWORD)
                    logger.info(f"Instaloader authenticated as user: {settings.INSTAGRAM_USERNAME}")
                except Exception as e:
                    logger.warning(f"Instaloader login failed (falling back to anonymous): {e}")

            self._loader = loader
        return self._loader

    def _fetch_via_meta_crawler(self, shortcode: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetches post caption, author, and image URL via social crawler OpenGraph metadata."""
        canonical_url = f"https://www.instagram.com/p/{shortcode}/"

        for user_agent in self.CRAWLER_USER_AGENTS:
            try:
                headers = {
                    "User-Agent": user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                }
                try:
                    res = requests.get(
                        canonical_url,
                        headers=headers,
                        timeout=settings.REQUEST_TIMEOUT_SECONDS,
                        verify=settings.SSL_VERIFY,
                    )
                except requests.exceptions.SSLError:
                    res = requests.get(
                        canonical_url,
                        headers=headers,
                        timeout=settings.REQUEST_TIMEOUT_SECONDS,
                        verify=False,
                    )

                if res.status_code == 200 and res.text:
                    soup = BeautifulSoup(res.text, "html.parser")
                    og_desc = (
                        soup.find("meta", property="og:description")
                        or soup.find("meta", attrs={"name": "description"})
                    )
                    og_image = (
                        soup.find("meta", property="og:image")
                        or soup.find("meta", attrs={"name": "twitter:image"})
                    )
                    image_url = og_image["content"].strip() if og_image and og_image.get("content") else None

                    if og_desc and og_desc.get("content"):
                        raw_caption = og_desc["content"].strip()
                        if raw_caption:
                            # Extract author if present in format "... - username on Date: ..."
                            owner = None
                            author_match = re.search(r"-\s*([a-zA-Z0-9._]+)\s+on\s+[A-Za-z]+", raw_caption)
                            if author_match:
                                owner = author_match.group(1)

                            logger.info(f"Successfully retrieved Instagram caption via meta crawler for {shortcode} (len: {len(raw_caption)})")
                            return raw_caption, owner, image_url
            except Exception as e:
                logger.debug(f"Meta crawler attempt failed with user-agent {user_agent}: {e}")

        return None, None, None

    def _fetch_via_instaloader(self, shortcode: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetches post caption, owner username, and display url via Instaloader."""
        try:
            loader = self._get_loader()
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            caption = post.caption
            owner = post.owner_username
            image_url = getattr(post, "url", None)
            return caption, owner, image_url
        except iexceptions.ProfileNotExistsException as e:
            logger.warning(f"Instagram post/profile does not exist ({shortcode}): {e}")
            return None, None, None
        except (iexceptions.PrivateProfileNotFollowedException, iexceptions.LoginRequiredException) as e:
            logger.warning(f"Instagram post requires login or is private ({shortcode}): {e}")
            return None, None, None
        except iexceptions.ConnectionException as e:
            logger.warning(f"Instaloader connection error for {shortcode}: {e}")
            return None, None, None
        except Exception as e:
            logger.warning(f"Instaloader error for {shortcode}: {e}")
            return None, None, None

    async def extract_recipe(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Extracts structured recipe from Instagram post or reel caption."""
        shortcode = self.extract_shortcode(url)
        if not shortcode:
            raise ValueError(f"Unable to extract Instagram shortcode from URL: {url}")

        logger.info(f"Processing Instagram shortcode: {shortcode}")

        # 1. Primary: Fast and highly reliable OpenGraph social crawler
        caption, owner, image_url = await asyncio.to_thread(self._fetch_via_meta_crawler, shortcode)

        # 2. Fallback: Instaloader GraphQL
        if not caption:
            logger.info("Meta crawler returned no caption; attempting Instaloader fallback...")
            caption, owner, image_url = await asyncio.to_thread(self._fetch_via_instaloader, shortcode)

        extraction_method = "llm"
        if not caption or not caption.strip():
            # If caption is missing but we have post context or creator username
            if owner or shortcode:
                logger.info(f"Instagram caption unavailable. Attempting title/creator inferred extraction for {shortcode}")
                caption = (
                    f"INSTAGRAM POST SHORTCODE: {shortcode} | CREATOR: @{owner or 'unknown'}\n"
                    f"(Note: Post caption was inaccessible. If this post reference describes a culinary recipe/dish, "
                    f"infer standard authentic ingredients and instructions. If it is NOT a recipe, mark is_recipe=false.)"
                )
                extraction_method = "llm_title_inferred"
            else:
                raise RuntimeError(
                    f"Could not retrieve caption or metadata from Instagram post ({url}). "
                    "The post might be private, deleted, or Instagram access restrictions may be active."
                )

        # Prepare context payload for LLM
        context_hint = f"Platform: Instagram Reel/Post | Shortcode: {shortcode}"
        if owner:
            context_hint += f" | Creator: @{owner}"

        # Extract structured output via Azure OpenAI
        extracted = await llm_service.extract_recipe_structured_async(
            raw_text=caption,
            platform_context=context_hint
        )

        images = [image_url] if image_url else []

        recipe_detail = RecipeDetailModel(
            name=extracted.name,
            images=images,
            course=extracted.course or "Lunch",
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
            sourceType="instagram",
            extractionMethod=extraction_method,
        )

        return RecipeResponse(recipeDetail=recipe_detail)
