"""Azure Cosmos DB service for persisting and querying structured recipes."""

import asyncio
import hashlib
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.identity import DefaultAzureCredential
from app.config import settings
from app.schemas.recipe import RecipeResponse
from app.utils.logger import logger


class CosmosService:
    """Singleton service managing Azure Cosmos DB operations for recipes."""

    _instance: Optional["CosmosService"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._client: Optional[CosmosClient] = None
        self._database = None
        self._container = None
        self._initialize()

    @classmethod
    def get_instance(cls) -> "CosmosService":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _initialize(self) -> None:
        """Initializes the Cosmos DB client, database, and container clients."""
        if not settings.is_cosmos_configured:
            logger.info(
                "Cosmos DB endpoint not configured (COSMOS_DB_ENDPOINT / COSMOS_DB_URL missing). "
                "Database persistence is disabled."
            )
            return

        # Attempt connection: First with Key if provided, fallback to DefaultAzureCredential (AAD), or vice versa
        credentials_to_try = []
        if settings.COSMOS_DB_KEY and settings.COSMOS_DB_KEY.strip():
            credentials_to_try.append(("Account Key", settings.COSMOS_DB_KEY))
        credentials_to_try.append(("Azure AD (DefaultAzureCredential)", DefaultAzureCredential()))

        last_error = None
        for auth_type, credential in credentials_to_try:
            try:
                logger.info(f"Connecting to Azure Cosmos DB using {auth_type}...")
                client = CosmosClient(
                    url=settings.COSMOS_DB_ENDPOINT,
                    credential=credential,
                    connection_verify=settings.SSL_VERIFY,
                )

                # Try connecting to existing database and container
                database = client.get_database_client(settings.COSMOS_DB_DATABASE)
                container = database.get_container_client(settings.COSMOS_DB_CONTAINER)

                # Validate connectivity by reading container properties
                container.read()

                self._client = client
                self._database = database
                self._container = container
                logger.info(
                    f"Azure Cosmos DB successfully connected and verified via {auth_type} "
                    f"(database: '{settings.COSMOS_DB_DATABASE}', container: '{settings.COSMOS_DB_CONTAINER}')"
                )
                return
            except Exception as e:
                last_error = e
                logger.warning(f"Cosmos DB connection attempt via {auth_type} failed: {e}")

        logger.error(f"Failed to initialize Azure Cosmos DB after trying all authentication methods: {last_error}")
        self._client = None
        self._database = None
        self._container = None

    def is_ready(self) -> bool:
        """Checks if Cosmos DB client and container are ready."""
        return bool(self._client and self._container)

    @staticmethod
    def generate_recipe_id(source_url: str) -> str:
        """Generates a stable, unique ID for a recipe based on its source URL."""
        url_hash = hashlib.sha256(source_url.strip().lower().encode("utf-8")).hexdigest()[:16]
        return f"rec_{url_hash}"

    def save_recipe(self, recipe: RecipeResponse) -> Tuple[bool, Optional[str]]:
        """Saves or updates a recipe document in Cosmos DB.
        
        Returns:
            Tuple of (success: bool, recipe_id: Optional[str])
        """
        if not self.is_ready():
            logger.debug("Cosmos DB is not configured; skipping persistence.")
            return False, None

        try:
            detail = recipe.recipeDetail
            if detail.recipeId:
                doc_id = detail.recipeId
            elif detail.sourceUrl:
                existing_recipe = self.get_recipe_by_source_url(detail.sourceUrl)
                doc_id = (
                    existing_recipe.get("recipeId")
                    or existing_recipe.get("id")
                    if existing_recipe
                    else self.generate_recipe_id(detail.sourceUrl)
                )
            else:
                doc_id = detail.id or str(uuid.uuid4()).upper()
            detail.id = doc_id
            detail.recipeId = doc_id

            # Dump Pydantic model to dict
            doc_data: Dict[str, Any] = recipe.model_dump()
            doc_data["id"] = doc_id
            doc_data["recipeId"] = doc_id

            # Upsert into container
            self._container.upsert_item(body=doc_data)
            logger.info(f"Successfully saved recipe '{detail.name}' (ID / recipeId: {doc_id}) to Cosmos DB.")
            return True, doc_id

        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Cosmos DB HTTP error saving recipe: {e.message} (status: {e.status_code})")
            return False, None
        except Exception as e:
            logger.error(f"Unexpected error saving recipe to Cosmos DB: {e}")
            return False, None

    def get_recipe(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a recipe by its recipeId (partition key)."""
        if not self.is_ready():
            return None

        try:
            # Direct point read using recipeId as the partition key
            return self._container.read_item(item=recipe_id, partition_key=recipe_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error reading recipe '{recipe_id}' from Cosmos DB: {e}")
            return None

    def get_recipe_by_source_url(self, source_url: str) -> Optional[Dict[str, Any]]:
        """Retrieves the most recent recipe document saved for a source URL."""
        if not self.is_ready():
            return None

        normalized_url = source_url.strip()
        alternate_url = normalized_url.rstrip("/") if normalized_url.endswith("/") else f"{normalized_url}/"

        try:
            stable_recipe_id = self.generate_recipe_id(normalized_url)
            try:
                return self._container.read_item(item=stable_recipe_id, partition_key=stable_recipe_id)
            except exceptions.CosmosResourceNotFoundError:
                pass

            items = list(self._container.query_items(
                query=(
                    "SELECT * FROM c WHERE c.recipeDetail.sourceUrl = @source_url "
                    "OR c.recipeDetail.sourceUrl = @alternate_url ORDER BY c._ts DESC"
                ),
                parameters=[
                    {"name": "@source_url", "value": normalized_url},
                    {"name": "@alternate_url", "value": alternate_url},
                ],
                max_item_count=1,
                enable_cross_partition_query=True,
            ))
            return items[0] if items else None
        except Exception as e:
            logger.error(f"Error reading recipe by source URL from Cosmos DB: {e}")
            return None

    def update_recipe(self, recipe_id: str, recipe: RecipeResponse) -> Optional[Dict[str, Any]]:
        """Updates an existing recipe document in Cosmos DB by recipeId."""
        if not self.is_ready():
            return None

        try:
            self._container.read_item(item=recipe_id, partition_key=recipe_id)

            detail = recipe.recipeDetail
            detail.id = recipe_id
            detail.recipeId = recipe_id
            detail.savedToDb = True

            doc_data: Dict[str, Any] = recipe.model_dump()
            doc_data["id"] = recipe_id
            doc_data["recipeId"] = recipe_id

            return self._container.replace_item(
                item=recipe_id,
                body=doc_data,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Cosmos DB HTTP error updating recipe '{recipe_id}': {e.message} (status: {e.status_code})")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating recipe '{recipe_id}' in Cosmos DB: {e}")
            raise

    def list_recipes(self, limit: int = 50, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists recently saved recipeDetail documents from Cosmos DB."""
        if not self.is_ready():
            return []

        try:
            if source_type:
                query = "SELECT * FROM c WHERE c.recipeDetail.sourceType = @source_type ORDER BY c._ts DESC"
                parameters = [{"name": "@source_type", "value": source_type}]
            else:
                query = "SELECT * FROM c ORDER BY c._ts DESC"
                parameters = []

            items = list(self._container.query_items(
                query=query,
                parameters=parameters,
                max_item_count=limit,
                enable_cross_partition_query=True
            ))
            return items[:limit]
        except Exception as e:
            logger.error(f"Error listing recipes from Cosmos DB: {e}")
            return []

    async def save_recipe_async(self, recipe: RecipeResponse) -> Tuple[bool, Optional[str]]:
        """Asynchronously saves recipe to Cosmos DB in a worker thread."""
        return await asyncio.to_thread(self.save_recipe, recipe)

    async def get_recipe_async(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        """Asynchronously retrieves a recipe by recipeId from Cosmos DB."""
        return await asyncio.to_thread(self.get_recipe, recipe_id)

    async def get_recipe_by_source_url_async(self, source_url: str) -> Optional[Dict[str, Any]]:
        """Asynchronously retrieves the most recent recipe by source URL."""
        return await asyncio.to_thread(self.get_recipe_by_source_url, source_url)

    async def update_recipe_async(self, recipe_id: str, recipe: RecipeResponse) -> Optional[Dict[str, Any]]:
        """Asynchronously updates recipe in Cosmos DB."""
        return await asyncio.to_thread(self.update_recipe, recipe_id, recipe)

    async def list_recipes_async(self, limit: int = 50, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Asynchronously lists recipes from Cosmos DB."""
        return await asyncio.to_thread(self.list_recipes, limit, source_type)


# Global singleton instance
cosmos_service = CosmosService.get_instance()
