"""API v1 endpoint route definitions."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.config import settings
from app.schemas.recipe import RecipeRequest, RecipeResponse, SupportedPlatformsResponse
from app.services.cosmos_service import cosmos_service
from app.services.extractor_router import extractor_router
from app.services.llm_service import llm_service
from app.utils.logger import logger

router = APIRouter(prefix="/api/v1", tags=["Recipe Extraction"])


@router.post(
    "/extract-recipe",
    response_model=RecipeResponse,
    summary="Extract structured recipe from URL",
    description=(
        "Accepts a Web Page URL, YouTube video/short URL, Instagram Reel/Post URL, Facebook Post URL, or TikTok URL, "
        "extracts a standardized JSON recipe, and persists it into Azure Cosmos DB if configured."
    ),
    responses={
        200: {"description": "Recipe successfully extracted"},
        400: {"description": "Invalid URL or malformed request"},
        422: {"description": "Source content unavailable (no captions, private post, etc.)"},
        500: {"description": "Internal server or LLM extraction failure"},
    }
)
async def extract_recipe(payload: RecipeRequest) -> RecipeResponse:
    """Main extraction endpoint routing to YouTube, Instagram, Facebook, TikTok, or Web extractors."""
    url_str = str(payload.url)
    logger.info(f"Incoming recipe extraction request for URL: {url_str} (force_llm={payload.force_llm})")

    try:
        response = await extractor_router.route_and_extract(
            url=url_str,
            force_llm=payload.force_llm
        )

        # -------------------------------------------------------------
        # Cosmos DB Persistence
        # -------------------------------------------------------------
        if settings.COSMOS_DB_AUTO_SAVE and cosmos_service.is_ready():
            try:
                saved, doc_id = await cosmos_service.save_recipe_async(response)
                response.recipeDetail.savedToDb = saved
                if doc_id:
                    response.recipeDetail.id = doc_id
                    response.recipeDetail.recipeId = doc_id
            except Exception as e:
                logger.warning(f"Failed to auto-save recipe to Cosmos DB: {e}")
                response.recipeDetail.savedToDb = False

        return response

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Validation error for {url_str}: {error_msg}")
        if "not contain a recipe" in error_msg.lower() or "not a recipe" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_msg
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    except RuntimeError as e:
        error_msg = str(e)
        logger.error(f"Extraction runtime error for {url_str}: {error_msg}")
        if "No captions" in error_msg or "private account" in error_msg or "does not exist" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_msg
            )
        elif "Azure OpenAI" in error_msg or "authentication" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_msg
            )
    except Exception as e:
        logger.exception(f"Unhandled exception during extraction for {url_str}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while extracting the recipe: {str(e)}"
        )


@router.get(
    "/recipes",
    summary="List saved recipes from Cosmos DB",
    description="Retrieves a list of saved recipes previously extracted and stored in Azure Cosmos DB."
)
async def list_recipes(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of recipes to return"),
    source_type: Optional[str] = Query(None, description="Filter by platform (youtube, instagram, facebook, tiktok, web)")
):
    """Lists saved recipes from Cosmos DB."""
    if not cosmos_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cosmos DB is not configured or reachable. Check COSMOS_DB_ENDPOINT / COSMOS_DB_URL."
        )
    items = await cosmos_service.list_recipes_async(limit=limit, source_type=source_type)
    return {"count": len(items), "recipes": items}


@router.get(
    "/recipes/{recipe_id}",
    summary="Get saved recipe by ID from Cosmos DB",
    description="Retrieves a specific recipe document from Azure Cosmos DB by its recipeId partition key."
)
async def get_recipe_by_id(recipe_id: str):
    """Retrieves a recipe document by recipeId."""
    if not cosmos_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cosmos DB is not configured or reachable. Check COSMOS_DB_ENDPOINT / COSMOS_DB_URL."
        )
    recipe = await cosmos_service.get_recipe_async(recipe_id)
    if not recipe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe with ID '{recipe_id}' not found in Cosmos DB."
        )
    return recipe


@router.get(
    "/supported-platforms",
    response_model=SupportedPlatformsResponse,
    summary="List supported URL platforms and formats",
    description="Returns metadata about all supported sources (YouTube, Instagram, Facebook, TikTok, Web) and sample URLs."
)
def get_supported_platforms() -> SupportedPlatformsResponse:
    """Returns platform metadata and supported URL patterns."""
    return extractor_router.get_supported_platforms()


@router.get(
    "/health",
    summary="Health check and configuration status",
    description="Returns service uptime status and Azure OpenAI / Cosmos DB connectivity readiness."
)
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app_title": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "azure_openai": {
            "configured": settings.is_openai_configured,
            "endpoint": settings.AZURE_OPENAI_ENDPOINT if settings.is_openai_configured else None,
            "deployment": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            "api_version": settings.AZURE_OPENAI_API_VERSION,
            "ready": llm_service.is_ready()
        },
        "cosmos_db": {
            "configured": settings.is_cosmos_configured,
            "endpoint": settings.COSMOS_DB_ENDPOINT if settings.is_cosmos_configured else None,
            "database": settings.COSMOS_DB_DATABASE,
            "container": settings.COSMOS_DB_CONTAINER,
            "auto_save": settings.COSMOS_DB_AUTO_SAVE,
            "ready": cosmos_service.is_ready()
        }
    }
