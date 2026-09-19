"""Application configuration management with Azure Key Vault & APIM support."""

import os
from typing import Optional
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()


class Settings:
    """Configuration settings populated from Azure Key Vault and environment variables."""

    def __init__(self):
        # Application info
        self.APP_TITLE: str = os.getenv("APP_TITLE", "BEES-Recipes Extraction API")
        self.APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
        self.APP_DESCRIPTION: str = (
            "Production-ready multi-platform recipe extraction API for YouTube, Instagram, and Web URLs "
            "with Schema.org scraping and Azure OpenAI Structured Outputs."
        )
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development"))
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # Key Vault configuration
        self.KEY_VAULT_NAME: Optional[str] = (
            os.getenv("KEY_VAULT_NAME")
            or os.getenv("KeyVaultName")
            or "dcs-key-d-we-001"
        )
        self._keyvault_secrets = {}
        if self.KEY_VAULT_NAME and self.KEY_VAULT_NAME.strip():
            self._load_keyvault_secrets()

        # Azure OpenAI / APIM configuration. APIM takes precedence when configured.
        self.AZURE_OPENAI_APIM_ENDPOINT: Optional[str] = (
            self._keyvault_secrets.get("azure-openai-apim-endpoint")
            or os.getenv("AZUREOPENAI_APIM_API_ENDPOINT")
            or os.getenv("AZURE_OPENAI_APIM_ENDPOINT")
        )
        if self.AZURE_OPENAI_APIM_ENDPOINT:
            self.AZURE_OPENAI_APIM_ENDPOINT = self.AZURE_OPENAI_APIM_ENDPOINT.rstrip("/")
            if self.AZURE_OPENAI_APIM_ENDPOINT.lower().endswith("/openai"):
                self.AZURE_OPENAI_APIM_ENDPOINT = self.AZURE_OPENAI_APIM_ENDPOINT[:-len("/openai")]
        self.AZURE_OPENAI_APIM_API_KEY: Optional[str] = (
            self._keyvault_secrets.get("azure-openai-apim-key")
            or os.getenv("AZUREOPENAI_APIM_API_KEY")
            or os.getenv("AZURE_OPENAI_APIM_API_KEY")
        )

        self.AZURE_OPENAI_ENDPOINT: Optional[str] = (
            self.AZURE_OPENAI_APIM_ENDPOINT
            or self._keyvault_secrets.get("azure-openai-endpoint")
            or os.getenv("AZURE_OPENAI_ENDPOINT")
            or os.getenv("AZUREOPENAI_API_ENDPOINT")
        )

        self.AZURE_OPENAI_API_KEY: Optional[str] = (
            self.AZURE_OPENAI_APIM_API_KEY
            or self._keyvault_secrets.get("azure-openai-api-key")
            or os.getenv("AZURE_OPENAI_API_KEY")
            or os.getenv("AZUREOPENAI_API_KEY")
        )

        self.AZURE_OPENAI_DEPLOYMENT_NAME: str = (
            os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
            or os.getenv("AZUREOPENAI_API_LLM")
            or os.getenv("AZUREOPENAI_DEPLOYMENT_NAME")
            or "gpt-5.4"
        )

        self.AZURE_OPENAI_API_VERSION: str = (
            os.getenv("AZURE_OPENAI_API_VERSION")
            or os.getenv("AZUREOPENAI_API_VERSION")
            or "2024-08-01-preview"
        )

        # Optional APIM custom header if required by enterprise gateway
        self.APIM_SUBSCRIPTION_KEY_HEADER: str = os.getenv(
            "APIM_SUBSCRIPTION_KEY_HEADER",
            "Ocp-Apim-Subscription-Key"
        )

        # Azure Cosmos DB Configuration
        self.COSMOS_DB_ENDPOINT: Optional[str] = (
            self._keyvault_secrets.get("cosmos-db-endpoint")
            or os.getenv("COSMOS_DB_ENDPOINT")
            or os.getenv("COSMOS_DB_URL")
            or os.getenv("COSMOS_ENDPOINT")
        )
        self.COSMOS_DB_KEY: Optional[str] = (
            self._keyvault_secrets.get("cosmos-db-key")
            or os.getenv("COSMOS_DB_KEY")
            or os.getenv("COSMOS_KEY")
            or os.getenv("COSMOS_PRIMARY_KEY")
        )
        self.COSMOS_DB_DATABASE: str = (
            os.getenv("COSMOS_DB_DATABASE")
            or os.getenv("COSMOS_DATABASE")
            or os.getenv("RECIPES_DATABASE")
            or os.getenv("CHATBOT_DATABASE")
            or "bees-recipes"
        )
        self.COSMOS_DB_CONTAINER: str = (
            os.getenv("COSMOS_DB_CONTAINER")
            or os.getenv("COSMOS_CONTAINER")
            or os.getenv("RECIPES_CONTAINER")
            or "bees-recipes"
        )
        self.COSMOS_DB_AUTO_SAVE: bool = os.getenv("COSMOS_DB_AUTO_SAVE", "true").lower() in ("true", "1", "yes")

        # Network & Scraping Settings
        self.REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30.0"))
        self.MAX_HTML_CHARS: int = int(os.getenv("MAX_HTML_CHARS", "15000"))
        self.SSL_VERIFY: bool = os.getenv("SSL_VERIFY", "true").lower() in ("true", "1", "yes")
        self.DEFAULT_USER_AGENT: str = os.getenv(
            "DEFAULT_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        # Instagram optional credentials (for private/rate-limited queries if available)
        self.INSTAGRAM_USERNAME: Optional[str] = os.getenv("INSTAGRAM_USERNAME")
        self.INSTAGRAM_PASSWORD: Optional[str] = os.getenv("INSTAGRAM_PASSWORD")

    def _load_keyvault_secrets(self) -> None:
        """Loads required secrets from Azure Key Vault if accessible."""
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            vault_url = f"https://{self.KEY_VAULT_NAME}.vault.azure.net/"
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_url, credential=credential)

            secrets_to_fetch = [
                "azure-openai-apim-endpoint",
                "azure-openai-apim-key",
                "azure-openai-endpoint",
                "azure-openai-api-key",
                "cosmos-db-endpoint",
                "cosmos-db-key",
            ]
            for secret_name in secrets_to_fetch:
                try:
                    secret_obj = client.get_secret(secret_name)
                    if secret_obj and secret_obj.value:
                        self._keyvault_secrets[secret_name] = secret_obj.value
                except Exception:
                    pass
        except Exception:
            pass

    @property
    def is_openai_configured(self) -> bool:
        """Returns True if minimum Azure OpenAI connection settings are present."""
        return bool(self.AZURE_OPENAI_ENDPOINT and self.AZURE_OPENAI_API_KEY)

    @property
    def is_apim_configured(self) -> bool:
        """Returns True when the configured Azure OpenAI endpoint is APIM."""
        return bool(self.AZURE_OPENAI_APIM_ENDPOINT and self.AZURE_OPENAI_APIM_API_KEY)

    @property
    def is_cosmos_configured(self) -> bool:
        """Returns True if Cosmos DB endpoint is configured."""
        return bool(self.COSMOS_DB_ENDPOINT)


settings = Settings()
