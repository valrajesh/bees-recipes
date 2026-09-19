"""Unit tests for Azure Cosmos DB service."""

from unittest.mock import MagicMock
import pytest
from azure.cosmos import exceptions
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
    mock_recipe.recipeDetail.id = "RANDOM-ID"
    mock_recipe.recipeDetail.recipeId = None
    mock_container.read_item.side_effect = exceptions.CosmosResourceNotFoundError
    mock_container.query_items.return_value = []

    success, doc_id = service.save_recipe(mock_recipe)
    assert success is True
    assert doc_id is not None
    assert doc_id == CosmosService.generate_recipe_id(mock_recipe.recipeDetail.sourceUrl)
    assert mock_recipe.recipeDetail.recipeId == doc_id
    assert mock_container.upsert_item.called
    saved_doc = mock_container.upsert_item.call_args[1]["body"]
    assert saved_doc["recipeId"] == doc_id


def test_cosmos_save_recipe_reuses_existing_source_url_document(mock_recipe):
    service = CosmosService()
    mock_container = MagicMock()
    mock_container.read_item.side_effect = exceptions.CosmosResourceNotFoundError
    mock_container.query_items.return_value = [
        {"id": "EXISTING-ID", "recipeId": "EXISTING-ID", "recipeDetail": {"sourceUrl": mock_recipe.recipeDetail.sourceUrl}}
    ]
    service._container = mock_container
    service._client = MagicMock()
    mock_recipe.recipeDetail.id = "NEW-RANDOM-ID"
    mock_recipe.recipeDetail.recipeId = None

    success, doc_id = service.save_recipe(mock_recipe)

    assert success is True
    assert doc_id == "EXISTING-ID"
    saved_doc = mock_container.upsert_item.call_args[1]["body"]
    assert saved_doc["id"] == "EXISTING-ID"
    assert saved_doc["recipeId"] == "EXISTING-ID"


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


def test_cosmos_get_recipe_by_source_url_queries_source_url_variants():
    service = CosmosService()
    mock_container = MagicMock()
    mock_container.read_item.side_effect = exceptions.CosmosResourceNotFoundError
    mock_container.query_items.return_value = [
        {"id": "rec_123", "recipeId": "rec_123", "recipeDetail": {"sourceUrl": "https://example.com/recipe/"}}
    ]
    service._container = mock_container
    service._client = MagicMock()

    res = service.get_recipe_by_source_url("https://example.com/recipe/")

    assert res is not None
    query_kwargs = mock_container.query_items.call_args.kwargs
    assert "c.recipeDetail.sourceUrl" in query_kwargs["query"]
    assert query_kwargs["max_item_count"] == 1
    assert query_kwargs["enable_cross_partition_query"] is True
    assert query_kwargs["parameters"] == [
        {"name": "@source_url", "value": "https://example.com/recipe/"},
        {"name": "@alternate_url", "value": "https://example.com/recipe"},
    ]


def test_cosmos_get_recipe_by_source_url_uses_stable_id_point_read():
    service = CosmosService()
    mock_container = MagicMock()
    stable_id = CosmosService.generate_recipe_id("https://example.com/recipe/")
    mock_container.read_item.return_value = {"id": stable_id, "recipeId": stable_id}
    service._container = mock_container
    service._client = MagicMock()

    res = service.get_recipe_by_source_url("https://example.com/recipe/")

    assert res["id"] == stable_id
    mock_container.read_item.assert_called_once_with(item=stable_id, partition_key=stable_id)
    mock_container.query_items.assert_not_called()


def test_cosmos_update_recipe_replaces_existing_document(mock_recipe):
    service = CosmosService()
    mock_container = MagicMock()
    mock_container.read_item.return_value = {"id": "rec_test123", "recipeId": "rec_test123"}
    mock_container.replace_item.return_value = mock_recipe.model_dump()
    service._container = mock_container
    service._client = MagicMock()

    updated = service.update_recipe("rec_test123", mock_recipe)

    assert updated is not None
    mock_container.read_item.assert_called_once_with(item="rec_test123", partition_key="rec_test123")
    mock_container.replace_item.assert_called_once()
    replace_kwargs = mock_container.replace_item.call_args.kwargs
    assert replace_kwargs["item"] == "rec_test123"
    assert replace_kwargs["body"]["id"] == "rec_test123"
    assert replace_kwargs["body"]["recipeId"] == "rec_test123"
    assert replace_kwargs["body"]["recipeDetail"]["savedToDb"] is True


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
