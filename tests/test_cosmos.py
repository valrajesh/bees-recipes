"""Unit tests for Azure Cosmos DB service."""

from unittest.mock import MagicMock
import pytest
from app.schemas.recipe import (
    IngredientModel,
    InstructionModel,
    LocalizedText,
    RecipeDetailModel,
    RecipeResponse,
)
from app.services.cosmos_service import CosmosService


@pytest.fixture
def mock_recipe():
    detail = RecipeDetailModel(
        id="rec_test123",
        recipeId="rec_test123",
        name="Spiced Chickpeas",
        images=["https://example.com/img.jpg"],
        course="Snack",
        duration=30,
        storeType="Colruyt",
        numberOfServings=4,
        nutriScore="B",
        tips=[],
        nutritions=[],
        instructions=[InstructionModel(title="", description="Bake at 200C", ingredients=[])],
        ingredients=[IngredientModel(amount=1.0, name=LocalizedText(singular="chickpeas", plural="chickpeas"))],
        sourceUrl="https://youtube.com/shorts/sample123",
        sourceType="youtube",
        extractionMethod="llm",
    )
    return RecipeResponse(recipeDetail=detail)


def test_cosmos_id_generation():
    url = "https://www.youtube.com/shorts/h8MHptcwKwk"
    doc_id = CosmosService.generate_recipe_id(url)
    assert doc_id.startswith("rec_")
    assert len(doc_id) > 10


def test_cosmos_save_recipe_when_ready(mock_recipe):
    service = CosmosService()
    mock_container = MagicMock()
    service._container = mock_container
    service._client = MagicMock()

    success, doc_id = service.save_recipe(mock_recipe)
    assert success is True
    assert doc_id is not None
    assert mock_recipe.recipeDetail.recipeId == doc_id
    assert mock_container.upsert_item.called
    saved_doc = mock_container.upsert_item.call_args[1]["body"]
    assert saved_doc["recipeId"] == doc_id


def test_cosmos_get_recipe(mock_recipe):
    service = CosmosService()
    mock_container = MagicMock()
    mock_container.read_item.return_value = {"id": "rec_123", "recipeId": "rec_123", "name": "Test"}
    service._container = mock_container
    service._client = MagicMock()

    res = service.get_recipe("rec_123")
    assert res is not None
    assert res["name"] == "Test"
    assert res["recipeId"] == "rec_123"
    mock_container.read_item.assert_called_once_with(item="rec_123", partition_key="rec_123")


def test_cosmos_list_recipes_uses_recipe_detail_schema():
    service = CosmosService()
    mock_container = MagicMock()
    mock_container.query_items.return_value = [
        {"recipeId": "rec_1", "recipeDetail": {"name": "Soup", "sourceType": "web"}}
    ]
    service._container = mock_container

    recipes = service.list_recipes(limit=10, source_type="web")

    assert len(recipes) == 1
    assert recipes[0]["recipeDetail"]["name"] == "Soup"
    query = mock_container.query_items.call_args.kwargs["query"]
    assert "c.recipeDetail.sourceType" in query
    assert "c._ts" in query
