"""YouTube video and shorts recipe transcript extractor."""

import asyncio
import re
from typing import Optional, Tuple
import requests
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    CouldNotRetrieveTranscript,
)
from app.config import settings
from app.schemas.recipe import (
    RecipeDetailModel,
    RecipeResponse,
)
from app.services.extractors.base import BaseExtractor
from app.services.llm_service import llm_service
from app.utils.logger import logger


class YouTubeExtractor(BaseExtractor):
    """Extractor for YouTube videos, shorts, and embedded links."""

    YOUTUBE_REGEX = re.compile(
        r"(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})",
        re.IGNORECASE
    )

    @property
    def platform_name(self) -> str:
        return "youtube"

    def can_handle(self, url: str) -> bool:
        """Checks if the URL is a recognized YouTube video or short."""
        return bool(self.YOUTUBE_REGEX.search(url))

    def extract_video_id(self, url: str) -> Optional[str]:
        """Extracts the 11-character YouTube video ID."""
        match = self.YOUTUBE_REGEX.search(url)
        return match.group(1) if match else None

    def _create_http_session(self) -> requests.Session:
        """Creates a requests session configured with SSL and headers."""
        session = requests.Session()
        session.headers.update({"User-Agent": settings.DEFAULT_USER_AGENT})
        session.verify = settings.SSL_VERIFY
        return session

    def _fetch_video_metadata(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetches video title, author, and thumbnail image using the public YouTube oEmbed endpoint."""
        try:
            oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
            try:
                res = requests.get(
                    oembed_url,
                    timeout=5,
                    headers={"User-Agent": settings.DEFAULT_USER_AGENT},
                    verify=settings.SSL_VERIFY
                )
            except requests.exceptions.SSLError:
                res = requests.get(
                    oembed_url,
                    timeout=5,
                    headers={"User-Agent": settings.DEFAULT_USER_AGENT},
                    verify=False
                )
            if res.status_code == 200:
                data = res.json()
                return data.get("title"), data.get("author_name"), data.get("thumbnail_url")
        except Exception as e:
            logger.debug(f"Could not fetch YouTube oEmbed metadata: {e}")
        return None, None, None

    def _fetch_video_description(self, video_id: str) -> Optional[str]:
        """Fetches video description from YouTube watch page HTML as a fallback when captions are missing."""
        try:
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                "User-Agent": settings.DEFAULT_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
            try:
                res = requests.get(
                    watch_url,
                    headers=headers,
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                    verify=settings.SSL_VERIFY,
                )
            except requests.exceptions.SSLError:
                res = requests.get(
                    watch_url,
                    headers=headers,
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                    verify=False,
                )
            if res.status_code == 200:
                html = res.text
                # Find shortDescription in player response
                idx = html.find('"shortDescription":"')
                if idx != -1:
                    start_idx = idx + len('"shortDescription":"')
                    # Find closing quote respecting escapes
                    end_idx = start_idx
                    while end_idx < len(html):
                        if html[end_idx] == '"' and html[end_idx - 1] != '\\':
                            break
                        end_idx += 1
                    raw_desc = html[start_idx:end_idx]
                    # Decode unicode escapes and newlines
                    decoded = (
                        raw_desc.replace('\\n', '\n')
                        .replace('\\r', '')
                        .replace('\\"', '"')
                        .replace('\\\\', '\\')
                    )
                    return decoded.strip()
        except Exception as e:
            logger.warning(f"Failed to extract video description for {video_id}: {e}")
        return None

    def _fetch_transcript_text(self, video_id: str) -> str:
        """Fetches transcript text, supporting direct english, auto-generated, and translated transcripts."""
        session = self._create_http_session()
        api = YouTubeTranscriptApi(http_client=session)

        try:
            # 1. Fetch transcript list
            transcript_list = api.list(video_id)
            
            # 2. Try to find preferred english languages
            try:
                transcript = transcript_list.find_transcript(["en", "en-US", "en-GB", "en-CA", "en-AU"])
                entries = transcript.fetch()
                return " ".join([e.text if hasattr(e, "text") else e["text"] for e in entries])
            except (NoTranscriptFound, Exception):
                pass

            # 3. Look through available transcripts (auto-generated or translatable)
            for t in transcript_list:
                if t.language_code.startswith("en"):
                    entries = t.fetch()
                    return " ".join([e.text if hasattr(e, "text") else e["text"] for e in entries])
                if t.is_translatable:
                    translated = t.translate("en").fetch()
                    return " ".join([e.text if hasattr(e, "text") else e["text"] for e in translated])

            # 4. Fallback: fetch whatever transcript exists
            for t in transcript_list:
                entries = t.fetch()
                return " ".join([e.text if hasattr(e, "text") else e["text"] for e in entries])

            raise NoTranscriptFound(video_id, ["en"], None)
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            raise e
        except Exception as e:
            # If SSL error, retry with SSL verification disabled
            if "SSL" in str(e) or "certificate verify failed" in str(e).lower():
                logger.warning(f"Retrying YouTube transcript fetch for {video_id} with SSL verification disabled...")
                try:
                    fallback_session = requests.Session()
                    fallback_session.verify = False
                    fallback_api = YouTubeTranscriptApi(http_client=fallback_session)
                    transcript_list = fallback_api.list(video_id)
                    for t in transcript_list:
                        entries = t.fetch()
                        return " ".join([e.text if hasattr(e, "text") else e["text"] for e in entries])
                except Exception as inner_e:
                    raise CouldNotRetrieveTranscript(video_id) from inner_e
            raise CouldNotRetrieveTranscript(video_id) from e

    async def extract_recipe(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Extracts structured recipe from YouTube transcript or video description fallback."""
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError(f"Unable to extract YouTube video ID from URL: {url}")

        logger.info(f"Processing YouTube video ID: {video_id}")

        # Fetch video metadata concurrently
        title, author, thumbnail_url = await asyncio.to_thread(self._fetch_video_metadata, url)

        # 1. Attempt transcript fetching
        text_content = ""
        transcript_failed = False
        try:
            transcript_text = await asyncio.to_thread(self._fetch_transcript_text, video_id)
            if transcript_text and transcript_text.strip():
                text_content = f"TRANSCRIPT:\n{transcript_text}"
        except (TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript) as e:
            logger.info(f"Transcript unavailable for YouTube video {video_id}: {e}. Trying description fallback.")
            transcript_failed = True
        except VideoUnavailable as e:
            logger.error(f"YouTube video unavailable {video_id}: {e}")
            raise RuntimeError(f"YouTube video is private or unavailable: {url}") from e
        except Exception as e:
            logger.warning(f"Error fetching YouTube transcript for {video_id}: {e}. Trying description fallback.")
            transcript_failed = True

        # 2. If transcript is absent or short, fetch video description from page
        description = await asyncio.to_thread(self._fetch_video_description, video_id)
        if description and description.strip():
            if text_content:
                text_content += f"\n\nVIDEO DESCRIPTION:\n{description}"
            else:
                text_content = f"VIDEO DESCRIPTION:\n{description}"

        extraction_method = "llm"
        if not text_content.strip():
            if title and title.strip() and title.strip().lower() not in ["youtube", "video", "untitled"]:
                logger.info(f"Subtitles and description unavailable. Attempting LLM extraction inferred from video title: '{title}'")
                text_content = (
                    f"VIDEO TITLE: {title}\n"
                    f"(Note: Subtitles and description were unavailable. If this video title describes a cooking recipe/dish, "
                    f"infer standard authentic ingredients and instructions. If it is NOT a cooking recipe, set is_recipe=false.)"
                )
                extraction_method = "llm_title_inferred"
            else:
                raise RuntimeError(
                    f"Could not extract recipe from YouTube video ({url}). "
                    "Subtitles, video description, and metadata are unavailable."
                )

        # Prepare context payload for LLM
        context_hint = f"Platform: YouTube | Video ID: {video_id}"
        if title:
            context_hint += f" | Video Title: {title}"
        if author:
            context_hint += f" | Channel: {author}"

        # Extract structured output via Azure OpenAI
        title_inference_text = None
        if title:
            title_inference_text = (
                f"VIDEO TITLE: {title}\n"
                f"(Note: Transcript/description extraction did not produce usable ingredients or instructions. "
                f"If this video title describes a cooking recipe or dish, infer standard authentic ingredients and instructions. "
                f"If it is NOT a cooking recipe, set is_recipe=false.)"
            )
        extracted, used_title_retry = await llm_service.extract_recipe_with_title_retry_async(
            raw_text=text_content,
            platform_context=context_hint,
            title_inference_text=title_inference_text,
            title_platform_context=context_hint,
        )
        if used_title_retry:
            extraction_method = "llm_title_inferred"

        final_title = extracted.name
        if title and (not final_title or final_title.lower() in ["recipe", "extracted recipe", "untitled"]):
            final_title = title

        images = []
        if thumbnail_url:
            images.append(thumbnail_url)
        else:
            images.append(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")

        recipe_detail = RecipeDetailModel(
            name=final_title,
            images=images,
            course=extracted.course or "Main Course",
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
            sourceType="youtube",
            extractionMethod=extraction_method,
        )

        return RecipeResponse(recipeDetail=recipe_detail)
