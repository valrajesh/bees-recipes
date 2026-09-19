"""Integration tests for FastAPI endpoints."""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.recipe import (
    IngredientModel,
    InstructionModel,
    LocalizedText,
    RecipeDetailModel,
    RecipeResponse,
)

client = TestClient(app)


def test_root_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_api_v1_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "azure_openai" in data


def test_supported_platforms_endpoint():
    response = client.get("/api/v1/supported-platforms")
    assert response.status_code == 200
    data = response.json()
    assert "platforms" in data
    assert len(data["platforms"]) >= 5
    platform_ids = [p["identifier"] for p in data["platforms"]]
    assert "youtube" in platform_ids
    assert "instagram" in platform_ids
    assert "facebook" in platform_ids
    assert "tiktok" in platform_ids
    assert "web" in platform_ids


@pytest.mark.asyncio
async def test_extract_recipe_endpoint_success():
    detail = RecipeDetailModel(
        name="Lemon Chia Chickpea Balls",
        images=["https://example.com/balls.jpg"],
        course="Snack",
        duration=15,
        storeType="Colruyt",
        numberOfServings=4,
        nutriScore="B",
        tips=[],
        nutritions=[],
        instructions=[InstructionModel(title="", description="Blend all ingredients.", ingredients=[])],
        ingredients=[IngredientModel(amount=1.0, name=LocalizedText(singular="chickpeas", plural="chickpeas"))],
        sourceUrl="https://plantbasedjuniors.com/lemon-chia-chickpea-balls/",
        sourceType="web",
        extractionMethod="schema_scraper",
    )
    mock_response = RecipeResponse(recipeDetail=detail)

    with patch(
        "app.api.v1.endpoints.extractor_router.route_and_extract",
        new=AsyncMock(return_value=mock_response)
    ):
        response = client.post(
            "/api/v1/extract-recipe",
            json={"url": "https://plantbasedjuniors.com/lemon-chia-chickpea-balls/"}
        )
        assert response.status_code == 200
        json_data = response.json()
        assert "recipeDetail" in json_data
        assert json_data["recipeDetail"]["name"] == "Lemon Chia Chickpea Balls"
        assert json_data["recipeDetail"]["sourceType"] == "web"
        assert len(json_data["recipeDetail"]["ingredients"]) == 1
        assert len(json_data["recipeDetail"]["images"]) == 1


def test_extract_recipe_invalid_url():
    response = client.post(
        "/api/v1/extract-recipe",
        json={"url": "not-a-valid-url"}
    )
    assert response.status_code == 422  # Pydantic HttpUrl validation error


def test_list_recipes_endpoint():
    with patch("app.api.v1.endpoints.cosmos_service.is_ready", return_value=True), patch(
        "app.api.v1.endpoints.cosmos_service.list_recipes_async",
        new=AsyncMock(return_value=[
            {
                "id": "REC-1",
                "recipeId": "REC-1",
                "recipeDetail": {
                    "name": "Test Soup",
                    "sourceType": "web",
                    "images": [],
                },
            }
        ])
    ):
        response = client.get("/api/v1/recipes?limit=10&source_type=web")

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "recipes": [
            {
                "id": "REC-1",
                "recipeId": "REC-1",
                "recipeDetail": {
                    "name": "Test Soup",
                    "sourceType": "web",
                    "images": [],
                },
            }
        ],
    }


def test_update_recipe_endpoint_success():
    payload = RecipeResponse(
        recipeDetail=RecipeDetailModel(
            id="REC-1",
            recipeId="REC-1",
            name="Updated Soup",
            images=["https://example.com/soup.jpg"],
            instructions=[InstructionModel(title="", description="Simmer gently.", ingredients=[])],
            ingredients=[IngredientModel(amount=1.0, name=LocalizedText(singular="onion", plural="onions"))],
            sourceType="web",
        )
    )

    with patch("app.api.v1.endpoints.cosmos_service.is_ready", return_value=True), patch(
        "app.api.v1.endpoints.cosmos_service.update_recipe_async",
        new=AsyncMock(return_value=payload.model_dump())
    ):
        response = client.put("/api/v1/recipes/REC-1", json=payload.model_dump())

    assert response.status_code == 200
    data = response.json()
    assert data["recipeDetail"]["id"] == "REC-1"
    assert data["recipeDetail"]["recipeId"] == "REC-1"
    assert data["recipeDetail"]["name"] == "Updated Soup"


def test_update_recipe_endpoint_rejects_mismatched_id():
    payload = RecipeResponse(
        recipeDetail=RecipeDetailModel(
            id="REC-2",
            recipeId="REC-2",
            name="Updated Soup",
            images=[],
            instructions=[InstructionModel(title="", description="Simmer gently.", ingredients=[])],
            ingredients=[IngredientModel(amount=1.0, name=LocalizedText(singular="onion", plural="onions"))],
            sourceType="web",
        )
    )

    with patch("app.api.v1.endpoints.cosmos_service.is_ready", return_value=True):
        response = client.put("/api/v1/recipes/REC-1", json=payload.model_dump())

    assert response.status_code == 400
    assert "must match" in response.json()["detail"]


def test_update_recipe_endpoint_not_found():
    payload = RecipeResponse(
        recipeDetail=RecipeDetailModel(
            id="REC-1",
            recipeId="REC-1",
            name="Updated Soup",
            images=[],
            instructions=[InstructionModel(title="", description="Simmer gently.", ingredients=[])],
            ingredients=[IngredientModel(amount=1.0, name=LocalizedText(singular="onion", plural="onions"))],
            sourceType="web",
        )
    )

    with patch("app.api.v1.endpoints.cosmos_service.is_ready", return_value=True), patch(
        "app.api.v1.endpoints.cosmos_service.update_recipe_async",
        new=AsyncMock(return_value=None)
    ):
        response = client.put("/api/v1/recipes/REC-1", json=payload.model_dump())

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_extract_recipe_non_recipe_content_validation():
    with patch(
        "app.api.v1.endpoints.extractor_router.route_and_extract",
        new=AsyncMock(side_effect=ValueError("The provided URL does not contain a recipe: The video is a gaming tutorial."))
    ):
        response = client.post(
            "/api/v1/extract-recipe",
            json={"url": "https://www.youtube.com/watch?v=gaming12345"}
        )
        assert response.status_code == 422
        data = response.json()
        assert "not contain a recipe" in data["detail"]
