"""Base class interface for platform-specific recipe extractors."""

from abc import ABC, abstractmethod
from app.schemas.recipe import RecipeResponse


class BaseExtractor(ABC):
    """Abstract Base Class for all URL extractors."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Returns the identifier name of the platform (e.g. 'youtube', 'instagram', 'web')."""
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Determines if this extractor can process the given URL."""
        pass

    @abstractmethod
    async def extract_recipe(self, url: str, force_llm: bool = False) -> RecipeResponse:
        """Extracts and returns a structured RecipeResponse from the given URL."""
        pass
