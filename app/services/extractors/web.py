"""Standard Web recipe scraper with Schema.org fast-path and LLM fallback."""

import asyncio
import re
from typing import List, Optional
import requests
from recipe_scrapers import scrape_html, WebsiteNotImplementedError, NoSchemaFoundInWildMode
from app.config import settings
from app.schemas.recipe import (
    IngredientModel,
    InstructionModel,
    LocalizedText,
    NutritionModel,
    RecipeDetailModel,
    RecipeResponse,
    TipModel,
)
from app.services.extractors.base import BaseExtractor
from app.services.llm_service import llm_service
from app.utils.html_cleaner import clean_html_for_llm
from app.utils.logger import logger


class WebExtractor(BaseExtractor):
    """Extractor for arbitrary web recipes using recipe-scrapers and LLM fallback."""

    @property
    def platform_name(self) -> str:
        return "web"

    def can_handle(self, url: str) -> bool:
        """Handles any standard http/https web URL."""
        return url.startswith("http://") or url.startswith("https://")

    def _fetch_html(self, url: str) -> str:
        """Fetches raw HTML with standard browser headers and timeout."""
        headers = {
            "User-Agent": settings.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            res = requests.get(
                url,
                headers=headers,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
                verify=settings.SSL_VERIFY
            )
        except requests.exceptions.SSLError:
            logger.warning(f"SSL verification failed for {url}; retrying without certificate verification...")
            res = requests.get(
                url,
                headers=headers,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
                verify=False
            )
        res.raise_for_status()
        return res.text

    def _extract_title_hint(self, html: str) -> Optional[str]:
        """Extracts the best available page title for title-based inference."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            title_meta = (
                soup.find("meta", property="og:title")
                or soup.find("meta", attrs={"name": "twitter:title"})
            )
            if title_meta and title_meta.get("content"):
                return title_meta["content"].strip()
            if soup.title and soup.title.string:
                return soup.title.string.strip()
            h1 = soup.find("h1")
            if h1:
                return h1.get_text(separator=" ", strip=True)
        except Exception as e:
            logger.debug(f"Unable to extract title hint from HTML: {e}")
        return None

    def _parse_ingredient_line(self, line: str) -> IngredientModel:
        """Heuristic parser to break raw ingredient strings into structured IngredientModel."""
        clean_line = line.strip()
        pattern = r"^((?:\d+(?:\.\d+)?|\d+\/\d+|\d+\s+\d+\/\d+)?)\s*([a-zA-Z]+)?\s+(.*)$"
        match = re.match(pattern, clean_line)

        amount_val: Optional[float] = None
        unit_val: Optional[str] = None
        name_val = clean_line

        if match:
            raw_amt, raw_unit, raw_name = match.groups()
            if raw_amt:
                try:
                    if "/" in raw_amt:
                        parts = raw_amt.split()
                        if len(parts) == 2:
                            w, f = parts
                            num, den = f.split("/")
                            amount_val = float(w) + float(num) / float(den)
                        else:
                            num, den = raw_amt.split("/")
                            amount_val = float(num) / float(den)
                    else:
                        amount_val = float(raw_amt)
                except Exception:
                    amount_val = None

            units_whitelist = {
                "cup", "cups", "tbsp", "tablespoon", "tablespoons", "tsp", "teaspoon", "teaspoons",
                "oz", "ounce", "ounces", "lb", "pound", "pounds", "g", "gram", "grams", "kg", "ml", "l",
                "can", "cans", "pinch", "pinches", "clove", "cloves", "slice", "slices", "stalk", "stalks",
                "el", "kl", "teen", "tenen", "stuks"
            }
            if raw_unit and raw_unit.lower() in units_whitelist:
                unit_val = raw_unit.lower()
                name_val = raw_name
            else:
                name_val = f"{raw_unit or ''} {raw_name}".strip()

        unit_obj = LocalizedText(singular=unit_val, plural=unit_val) if unit_val else None
        return IngredientModel(
            amount=amount_val,
            name=LocalizedText(singular=name_val or clean_line, plural=name_val or clean_line),
            unit=unit_obj,
        )

    def _parse_instructions(self, raw_instructions: List[str] | str) -> List[InstructionModel]:
        """Converts raw instruction strings or list into structured InstructionModel items."""
        steps_list: List[str] = []
        if isinstance(raw_instructions, list):
            steps_list = [s.strip() for s in raw_instructions if s.strip()]
        elif isinstance(raw_instructions, str):
            steps_list = [s.strip() for s in raw_instructions.split("\n") if s.strip()]

        result: List[InstructionModel] = []
        for text in steps_list:
            clean_text = re.sub(r"^(?:Step\s*\d+[:.]?|\d+[.):])\s*", "", text, flags=re.IGNORECASE).strip()
            result.append(
                InstructionModel(
                    title="",
                    description=clean_text or text,
                    ingredients=[],
                )
            )
        return result

    def _extract_nutrients(self, nutrients_dict: dict) -> List[NutritionModel]:
        """Extracts nutrition list from scraper output dictionary if present."""
        if not nutrients_dict or not isinstance(nutrients_dict, dict):
            return []

        def _clean_num(val) -> Optional[float]:
            if not val:
                return None
            m = re.search(r"(\d+(?:\.\d+)?)", str(val))
            return float(m.group(1)) if m else None

        results = []
        mapping = [
            ("calories", "Energie", "kcal", "ENERGY"),
            ("proteinContent", "Eiwit", "g", "PROTEINS"),
            ("carbohydrateContent", "Koolhydraat", "g", "CARBO_HYDRATES"),
            ("fatContent", "Vet", "g", "FATS"),
            ("saturatedFatContent", "Verzadigd vet", "g", "SATURATED_FATS"),
            ("fiberContent", "Vezel", "g", "FATS"),
            ("sugarContent", "Suiker", "g", "SUGAR"),
            ("sodiumContent", "Zout", "g", "SALTS"),
        ]

        for key, name, unit, ntype in mapping:
            if key in nutrients_dict:
                num = _clean_num(nutrients_dict[key])
                if num is not None:
                    results.append(
                        NutritionModel(
                            name=name,
                            amount=num,
                            unit=unit,
                            type=ntype
                        )
                    )
        return results

    async def extract_recipe(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Extracts structured recipe from Web URL via Schema.org scraping or LLM fallback."""
        logger.info(f"Fetching web page content for: {url}")
        try:
            html = await asyncio.to_thread(self._fetch_html, url)
        except requests.HTTPError as e:
            raise RuntimeError(f"HTTP error fetching web page ({e.response.status_code}): {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to connect to web URL: {str(e)}") from e

        # -------------------------------------------------------------
        # 1. Fast Path: Schema.org / recipe-scrapers
        # -------------------------------------------------------------
        if not force_llm:
            try:
                scraper = scrape_html(html, org_url=url, wild_mode=True)
                raw_ingredients = scraper.ingredients()
                raw_instructions = scraper.instructions_list() or scraper.instructions()

                if raw_ingredients and raw_instructions:
                    logger.info(f"Successfully scraped recipe '{scraper.title()}' via Schema.org / recipe-scrapers.")

                    structured_ingredients = [self._parse_ingredient_line(i) for i in raw_ingredients]
                    structured_instructions = self._parse_instructions(raw_instructions)

                    # Extract metadata safely
                    title = scraper.title() or "Extracted Recipe"
                    description = None
                    try:
                        description = scraper.description()
                    except Exception:
                        pass

                    cuisine = None
                    try:
                        cuisine = scraper.cuisine()
                    except Exception:
                        pass

                    category = None
                    try:
                        category = scraper.category()
                    except Exception:
                        pass

                    servings = None
                    try:
                        servings = scraper.yields()
                    except Exception:
                        pass

                    prep_time = None
                    try:
                        prep_time = scraper.prep_time()
                    except Exception:
                        pass

                    cook_time = None
                    try:
                        cook_time = scraper.cook_time()
                    except Exception:
                        pass

                    total_time = None
                    try:
                        total_time = scraper.total_time()
                    except Exception:
                        pass

                    nutrients = None
                    try:
                        nutrients = self._extract_nutrients(scraper.nutrients())
                    except Exception:
                        pass

                    servings_num = 4
                    if servings:
                        m = re.search(r"\d+", str(servings))
                        if m:
                            servings_num = int(m.group(0))

                    # Extract image
                    images = []
                    try:
                        img = scraper.image()
                        if img:
                            images.append(img)
                    except Exception:
                        pass

                    recipe_detail = RecipeDetailModel(
                        name=title,
                        images=images,
                        course=category or cuisine or "Main Course",
                        duration=total_time or (prep_time or 0) + (cook_time or 0) or 30,
                        storeType="Colruyt",
                        numberOfServings=servings_num,
                        nutriScore="B",
                        nutriScoreUrl="https://www.colruytgroup.com/nl/bewust-consumeren/nutri-score",
                        tips=[],
                        nutritions=nutrients,
                        instructions=structured_instructions,
                        ingredients=structured_ingredients,
                        sourceUrl=url,
                        sourceType="web",
                        extractionMethod="schema_scraper",
                    )

                    return RecipeResponse(recipeDetail=recipe_detail)
            except (WebsiteNotImplementedError, NoSchemaFoundInWildMode) as e:
                logger.info(f"recipe-scrapers not supported or no schema found: {e}. Proceeding to LLM fallback.")
            except Exception as e:
                logger.warning(f"recipe-scrapers encountered error: {e}. Proceeding to LLM fallback.")

        # -------------------------------------------------------------
        # 2. Fallback Path: Clean HTML & extract via Azure OpenAI LLM
        # -------------------------------------------------------------
        logger.info(f"Executing LLM fallback extraction for web URL: {url}")
        cleaned_text = clean_html_for_llm(html, max_chars=settings.MAX_HTML_CHARS)
        title_hint = self._extract_title_hint(html)

        extraction_method = "llm"
        if not cleaned_text.strip():
            logger.info(f"Web HTML body text minimal/empty. Attempting URL/title inferred extraction: {url}")
            cleaned_text = (
                f"WEBSITE URL: {url}\n"
                f"(Note: Webpage body was minimal or JavaScript-protected. If this URL/title represents a culinary recipe/dish, "
                f"infer standard authentic ingredients and cooking instructions. If it is NOT a recipe, mark is_recipe=false.)"
            )
            extraction_method = "llm_title_inferred"

        title_inference_text = (
            f"WEBSITE URL: {url}\n"
            f"RECIPE TITLE OR PAGE TITLE: {title_hint or url}\n"
            f"(Note: The primary scraper and content-based LLM fallback did not produce usable ingredients or instructions. "
            f"If this title/URL represents a culinary recipe or dish, infer standard authentic ingredients and cooking instructions. "
            f"If it is NOT a recipe, mark is_recipe=false.)"
        )
        extracted, used_title_retry = await llm_service.extract_recipe_with_title_retry_async(
            raw_text=cleaned_text,
            platform_context=f"Website URL: {url}",
            title_inference_text=title_inference_text,
            title_platform_context=f"Website URL: {url} | Title: {title_hint or url}",
        )
        if used_title_retry:
            extraction_method = "llm_title_inferred"

        # Extract image from HTML if available
        images = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            og_img = (
                soup.find("meta", property="og:image")
                or soup.find("meta", attrs={"name": "twitter:image"})
            )
            if og_img and og_img.get("content"):
                images.append(og_img["content"].strip())
        except Exception:
            pass

        recipe_detail = RecipeDetailModel(
            name=extracted.name,
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
            sourceType="web",
            extractionMethod=extraction_method,
        )

        return RecipeResponse(recipeDetail=recipe_detail)
