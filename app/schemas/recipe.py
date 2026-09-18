"""Pydantic schemas for recipe extraction requests, responses, and LLM structured outputs matching the Colruyt recipeDetail schema."""

import uuid
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, HttpUrl


class LocalizedText(BaseModel):
    """Singular and plural forms of an ingredient or unit."""
    singular: Optional[str] = Field(None, description="Singular name or unit")
    plural: Optional[str] = Field(None, description="Plural name or unit")


class IngredientModel(BaseModel):
    """Structured representation of a recipe ingredient."""
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()).upper(),
        description="Unique GUID for the ingredient"
    )
    amount: Optional[float] = Field(None, description="Numeric quantity (e.g. 360, 2, 1.5)")
    name: LocalizedText = Field(..., description="Localized singular and plural name")
    unit: Optional[LocalizedText] = Field(None, description="Localized singular and plural unit")


class InstructionModel(BaseModel):
    """Structured representation of a single recipe step."""
    title: str = Field(default="", description="Optional title or timer annotation like '(30 min.)'")
    description: str = Field(default="", description="Detailed instructions for this step")
    ingredients: List[str] = Field(default_factory=list, description="Ingredient names referenced in this step")


class NutritionModel(BaseModel):
    """Nutritional value entry."""
    name: str = Field(..., description="Nutrient display name (e.g. 'Energie', 'Eiwit', 'Koolhydraat', 'Suiker', 'Verzadigd vet', 'Vezel', 'Zout')")
    amount: Optional[float] = Field(None, description="Nutrient numeric value")
    unit: Optional[str] = Field(None, description="Measurement unit (e.g. 'kcal', 'kj', 'g', 'mg')")
    type: Optional[str] = Field(
        None,
        description="Nutrient category code (e.g. 'ENERGY', 'PROTEINS', 'CARBO_HYDRATES', 'SUGAR', 'SATURATED_FATS', 'FIBRES', 'SALTS')"
    )


class TipModel(BaseModel):
    """Serving, wine/beverage pairing, or cooking advice."""
    type: str = Field(default="GENERAL", description="Tip category (e.g. 'BEVERAGES', 'WINE', 'BEER', 'GENERAL', 'STORAGE')")
    name: str = Field(..., description="Title or beverage type")
    description: str = Field(..., description="Tip details or pairing recommendation")


class LLMRecipeExtraction(BaseModel):
    """Model used with OpenAI Structured Outputs (client.beta.chat.completions.parse)."""
    is_recipe: bool = Field(
        True,
        description="Set to true if the content is a culinary recipe, food/drink preparation, or cooking guide. Set to false if the content is completely unrelated to food/cooking/recipes (e.g., gaming, music video, comedy, sports, tech review, news, general vlogs)."
    )
    rejection_reason: Optional[str] = Field(
        None,
        description="If is_recipe is false, provide a clear concise explanation of why this content is not a recipe (e.g., 'The provided video is a gaming tutorial and does not contain any cooking recipe')."
    )
    name: str = Field(..., description="Appetizing title/name of the recipe")
    course: Optional[str] = Field(None, description="Meal category (e.g. 'Lunch', 'Dinner', 'Breakfast', 'Dessert', 'Snack', 'Side')")
    duration: Optional[int] = Field(None, description="Total preparation + cooking duration in minutes")
    storeType: Optional[str] = Field("Colruyt", description="Store type / retail brand association")
    numberOfServings: Optional[int] = Field(4, description="Number of portions/servings")
    nutriScore: Optional[str] = Field(None, description="Nutri-Score grade (A, B, C, D, E)")
    tips: List[TipModel] = Field(default_factory=list, description="Tips, beverage/wine pairings, or storage advice")
    nutritions: List[NutritionModel] = Field(default_factory=list, description="List of nutritional breakdown items")
    instructions: List[InstructionModel] = Field(default_factory=list, description="Ordered list of cooking steps")
    ingredients: List[IngredientModel] = Field(default_factory=list, description="List of ingredients with singular/plural names and units")


class RecipeDetailModel(BaseModel):
    """Full detail model for a recipe."""
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()).upper(),
        description="Unique GUID identifier for the recipe"
    )
    recipeId: Optional[str] = Field(
        None,
        description="Partition key identifier for Cosmos DB (matches id)"
    )
    name: str = Field(..., description="Name of the recipe")
    images: List[str] = Field(default_factory=list, description="List of recipe image/thumbnail URLs")
    course: Optional[str] = Field(None, description="Course/category (e.g. 'Lunch', 'Dinner', 'Dessert')")
    duration: Optional[int] = Field(None, description="Total duration in minutes")
    storeType: Optional[str] = Field("Colruyt", description="Store association")
    numberOfServings: Optional[int] = Field(4, description="Number of portions")
    nutriScore: Optional[str] = Field(None, description="Nutri-Score value")
    nutriScoreUrl: Optional[str] = Field(
        "https://www.colruytgroup.com/nl/bewust-consumeren/nutri-score",
        description="Information link for Nutri-Score"
    )
    tips: List[TipModel] = Field(default_factory=list, description="Culinary tips and drink pairings")
    nutritions: List[NutritionModel] = Field(default_factory=list, description="Nutritional information items")
    instructions: List[InstructionModel] = Field(..., description="Step-by-step instructions")
    ingredients: List[IngredientModel] = Field(..., description="Ingredients with amounts and localized names")
    sourceUrl: Optional[str] = Field(None, description="Original URL from which the recipe was extracted")
    sourceType: Optional[Literal["youtube", "instagram", "facebook", "tiktok", "web", "unknown"]] = Field(
        None,
        description="Origin platform type"
    )
    extractionMethod: Optional[Literal["schema_scraper", "llm", "llm_title_inferred", "hybrid"]] = Field(
        None,
        description="Method used for extraction"
    )
    savedToDb: Optional[bool] = Field(None, description="Whether saved in Cosmos DB")


class RecipeResponse(BaseModel):
    """Response payload containing the recipeDetail object."""
    recipeDetail: RecipeDetailModel = Field(..., description="Structured recipe details")


class RecipeRequest(BaseModel):
    """Request payload for recipe extraction."""
    url: HttpUrl = Field(
        ...,
        description="Target URL to extract (YouTube video/short, Instagram post/reel, Facebook post, TikTok video, or Web page)",
        examples=["https://plantbasedjuniors.com/lemon-chia-chickpea-balls/", "https://www.youtube.com/shorts/h8MHptcwKwk"]
    )
    force_llm: bool = Field(
        False,
        description="If True, bypasses fast Schema.org scraping and forces deep LLM extraction"
    )


class SupportedPlatformsResponse(BaseModel):
    """Information on supported URL patterns and platforms."""
    platforms: List[dict] = Field(..., description="List of supported platforms with capabilities and example URLs")

