"""FastAPI application initialization and lifespan configuration."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.endpoints import router as api_v1_router
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info(f"Starting {settings.APP_TITLE} v{settings.APP_VERSION} ({settings.ENVIRONMENT})")
    if settings.is_openai_configured:
        logger.info(f"Azure OpenAI configured for endpoint: {settings.AZURE_OPENAI_ENDPOINT}")
    else:
        logger.warning("Azure OpenAI credentials not set. Some extractors will require configuration.")
    yield
    logger.info(f"Shutting down {settings.APP_TITLE}")


def create_app() -> FastAPI:
    """Factory creating and configuring the FastAPI application."""
    app = FastAPI(
        title=settings.APP_TITLE,
        version=settings.APP_VERSION,
        description=settings.APP_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Enable CORS for frontend and cross-origin consumer integrations
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(api_v1_router)

    # Root health endpoint
    @app.get("/health", tags=["System"])
    def root_health():
        return {
            "status": "ok",
            "app": settings.APP_TITLE,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
