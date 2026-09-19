"""Azure OpenAI client service utilizing Structured Outputs with Pydantic models."""

import asyncio
import threading
from typing import Optional
from openai import AzureOpenAI, APIError, RateLimitError, AuthenticationError
from app.config import settings
from app.schemas.recipe import LLMRecipeExtraction
from app.utils.logger import logger


class AzureOpenAIService:
    """Singleton service for Azure OpenAI / APIM Structured Outputs."""

    _instance: Optional["AzureOpenAIService"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._client: Optional[AzureOpenAI] = None
        self._initialize_client()

    @classmethod
    def get_instance(cls) -> "AzureOpenAIService":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _initialize_client(self) -> None:
        """Initializes the AzureOpenAI client with APIM / Azure settings."""
        if not settings.is_openai_configured:
            logger.warning(
                "Azure OpenAI is not fully configured (AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY missing). "
                "LLM fallback and social extraction will fail until configured."
            )
            self._client = None
            return

        default_headers = {}
        if settings.is_apim_configured:
            default_headers[settings.APIM_SUBSCRIPTION_KEY_HEADER] = settings.AZURE_OPENAI_APIM_API_KEY

        try:
            self._client = AzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                default_headers=default_headers if default_headers else None,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
            )
            logger.info(
                f"AzureOpenAI client successfully initialized ({'APIM' if settings.is_apim_configured else 'direct Azure OpenAI'}, "
                f"endpoint: {settings.AZURE_OPENAI_ENDPOINT}, "
                f"deployment: {settings.AZURE_OPENAI_DEPLOYMENT_NAME})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI client: {e}")
            self._client = None

    def is_ready(self) -> bool:
        """Checks if the OpenAI client is initialized and ready."""
        return self._client is not None

    def extract_recipe_structured(
        self,
        raw_text: str,
        platform_context: Optional[str] = None
    ) -> LLMRecipeExtraction:
        """Synchronously calls Azure OpenAI with Structured Outputs enforcing LLMRecipeExtraction schema."""
        if not self._client:
            raise RuntimeError(
                "Azure OpenAI client is not configured. Please set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY."
            )

        if not raw_text or not raw_text.strip():
            raise ValueError("Input text for recipe extraction is empty.")

        system_prompt = (
            "You are a professional culinary AI chef and recipe standardization expert.\n"
            "Your task is to analyze the provided text (YouTube transcript/description, Instagram/Facebook/TikTok caption, "
            "or scraped web page) and extract a complete, clean, structured recipe conforming strictly to the schema.\n\n"
            "CRITICAL VALIDATION & INFERENCE RULES:\n"
            "1. RECIPE RELEVANCE CHECK:\n"
            "   - First, determine if the provided content is related to food, cooking, baking, beverages, or culinary recipes.\n"
            "   - If YES: set 'is_recipe' to true and extract the full structured recipe.\n"
            "   - If NO (e.g. video games, music video, comedy, sports, tech, politics, news, general vlogs without cooking): "
            "set 'is_recipe' to false, describe why in 'rejection_reason' (e.g. 'The content is a video game walkthrough and contains no recipe'), "
            "set 'name' to the title, and leave ingredients/instructions empty.\n\n"
            "2. TITLE-BASED INFERENCE (WHEN TRANSCRIPT/DESCRIPTION IS MINIMAL OR MISSING):\n"
            "   - If the content is food-related but only provides a dish title or brief overview (e.g. 'How to make authentic Carbonara'), "
            "logically infer and synthesize standard, authentic ingredients, measurements, and cooking instructions for that dish.\n\n"
            "3. INGREDIENTS:\n"
            "   - 'amount': Numeric float quantity if stated (e.g. 360, 2, 1.5, 0.25). null if unquantified.\n"
            "   - 'name': An object with 'singular' (e.g. 'ui', 'wortel', 'kip') and 'plural' (e.g. 'uien', 'wortelen', 'kippen').\n"
            "   - 'unit': If a measurement unit exists, provide 'singular' (e.g. 'g', 'el', 'kl', 'ml', 'teen') and 'plural' (e.g. 'g', 'el', 'kl', 'ml', 'tenen'). If whole count, unit is null.\n\n"
            "4. INSTRUCTIONS:\n"
            "   - Ordered step-by-step cooking steps. Each step must have 'title' (optional annotation or timer like '(30 min.)' or empty '') and 'description' (the step action text).\n\n"
            "5. NUTRITIONS & TIPS:\n"
            "   - Extract or estimate standard macronutrients (name, amount, unit, type: 'ENERGY', 'PROTEINS', 'CARBO_HYDRATES', 'SUGAR', 'SATURATED_FATS', 'FIBRES', 'SALTS').\n"
            "   - If wine/beer pairings, chef tricks, or storage notes are suitable, extract as TipModel (type, name, description).\n\n"
            "6. COURSE, DURATION, SERVINGS:\n"
            "   - Infer course ('Lunch', 'Dinner', 'Dessert', 'Snack', 'Breakfast', 'Side'), duration in minutes (integer), and numberOfServings (integer)."
        )

        user_content = f"Source context: {platform_context or 'General'}\n\nContent to parse:\n{raw_text}"

        try:
            logger.info(f"Invoking Azure OpenAI parse() using deployment '{settings.AZURE_OPENAI_DEPLOYMENT_NAME}'...")
            response = self._client.beta.chat.completions.parse(
                model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format=LLMRecipeExtraction,
                temperature=0.1,
            )

            choice = response.choices[0]
            if choice.finish_reason == "length":
                logger.warning("LLM response reached maximum token length.")

            parsed_recipe: Optional[LLMRecipeExtraction] = choice.message.parsed
            if not parsed_recipe:
                refusal = getattr(choice.message, "refusal", None)
                raise RuntimeError(f"Model refused or failed to parse structured output: {refusal}")

            # Check if content was rejected as not a recipe
            if not parsed_recipe.is_recipe:
                reason = parsed_recipe.rejection_reason or "The provided URL does not contain any cooking or recipe content."
                logger.warning(f"Non-recipe content detected: {reason}")
                raise ValueError(f"The provided URL does not contain a recipe: {reason}")

            logger.info(f"Successfully extracted recipe: '{parsed_recipe.name}' with {len(parsed_recipe.ingredients)} ingredients.")
            return parsed_recipe

        except AuthenticationError as e:
            logger.error(f"Azure OpenAI Authentication Error: {e}")
            raise RuntimeError(f"Azure OpenAI authentication failed. Verify API key/APIM credentials: {e}") from e
        except RateLimitError as e:
            logger.error(f"Azure OpenAI Rate Limit Exceeded: {e}")
            raise RuntimeError(f"Azure OpenAI rate limit exceeded. Please retry shortly: {e}") from e
        except APIError as e:
            logger.error(f"Azure OpenAI API Error: {e}")
            raise RuntimeError(f"Azure OpenAI API error occurred: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during LLM recipe extraction: {e}")
            raise

    async def extract_recipe_structured_async(
        self,
        raw_text: str,
        platform_context: Optional[str] = None
    ) -> LLMRecipeExtraction:
        """Asynchronously calls the Azure OpenAI Structured Outputs extraction in a worker thread."""
        return await asyncio.to_thread(self.extract_recipe_structured, raw_text, platform_context)


# Global singleton instance
llm_service = AzureOpenAIService.get_instance()
