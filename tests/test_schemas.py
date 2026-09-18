"""Unit tests for Pydantic recipe schemas matching recipeDetail."""

from app.schemas.recipe import (
    IngredientModel,
    InstructionModel,
    LLMRecipeExtraction,
    LocalizedText,
    NutritionModel,
    RecipeDetailModel,
    RecipeRequest,
    RecipeResponse,
    TipModel,
)


def test_ingredient_item_creation():
    item = IngredientModel(
        amount=360,
        name=LocalizedText(singular="kip", plural="kippen"),
        unit=LocalizedText(singular="g", plural="g")
    )
    assert item.amount == 360
    assert item.name.singular == "kip"
    assert item.unit.singular == "g"
    assert item.id is not None


def test_instruction_step_creation():
    step = InstructionModel(
        title="(30 min.)",
        description="Breng water aan de kook en gaar de rijst.",
        ingredients=[]
    )
    assert step.title == "(30 min.)"
    assert "Breng water" in step.description


def test_llm_recipe_extraction_model():
    data = {
        "name": "Veggie kerrie",
        "course": "Lunch",
        "duration": 30,
        "storeType": "Colruyt",
        "numberOfServings": 4,
        "nutriScore": "B",
        "tips": [
            {
                "type": "BEVERAGES",
                "name": "Bier",
                "description": "Delta IPA"
            }
        ],
        "nutritions": [
            {
                "name": "Energie",
                "amount": 669,
                "unit": "kcal",
                "type": "ENERGY"
            }
        ],
        "instructions": [
            {
                "title": "",
                "description": "Cook rice.",
                "ingredients": []
            }
        ],
        "ingredients": [
            {
                "amount": 200,
                "name": {"singular": "erwtjes", "plural": "erwtjes"},
                "unit": {"singular": "g", "plural": "g"}
            }
        ]
    }
    extracted = LLMRecipeExtraction(**data)
    assert extracted.name == "Veggie kerrie"
    assert len(extracted.ingredients) == 1
    assert len(extracted.instructions) == 1
    assert extracted.nutritions[0].amount == 669


def test_recipe_response_serialization():
    detail = RecipeDetailModel(
        name="Test Recipe",
        images=["https://example.com/recipe.jpg"],
        course="Lunch",
        duration=30,
        storeType="Colruyt",
        numberOfServings=4,
        nutriScore="B",
        tips=[],
        nutritions=[],
        instructions=[InstructionModel(title="", description="Mix flour.", ingredients=[])],
        ingredients=[IngredientModel(amount=2, name=LocalizedText(singular="egg", plural="eggs"))],
        sourceUrl="https://example.com/recipe",
        sourceType="web",
        extractionMethod="schema_scraper",
        savedToDb=True,
    )
    resp = RecipeResponse(recipeDetail=detail)
    dumped = resp.model_dump()
    assert dumped["recipeDetail"]["name"] == "Test Recipe"
    assert dumped["recipeDetail"]["images"] == ["https://example.com/recipe.jpg"]
    assert dumped["recipeDetail"]["sourceType"] == "web"
    assert dumped["recipeDetail"]["savedToDb"] is True
