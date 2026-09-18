"""Schema definitions for BEES-Recipes API."""

from app.schemas.recipe import (
    IngredientModel,
    InstructionModel,
    LLMRecipeExtraction,
    LocalizedText,
    NutritionModel,
    RecipeDetailModel,
    RecipeRequest,
    RecipeResponse,
    SupportedPlatformsResponse,
    TipModel,
)

__all__ = [
    "LocalizedText",
    "IngredientModel",
    "InstructionModel",
    "NutritionModel",
    "TipModel",
    "LLMRecipeExtraction",
    "RecipeDetailModel",
    "RecipeRequest",
    "RecipeResponse",
    "SupportedPlatformsResponse",
]
