"""Trusted image proxy service for external recipe images."""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlparse
import requests
from requests.exceptions import SSLError
from app.config import settings


@dataclass(frozen=True)
class ProxiedImage:
    """Fetched image bytes and response metadata."""
    content: bytes
    media_type: str


class ImageProxyService:
    """Fetches external images through the API domain for app clients."""

    _blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

    def build_proxy_url(self, image_url: str, base_url: str) -> str:
        """Builds an absolute API proxy URL for an external image URL."""
        if self.is_proxy_url(image_url) or not self.is_supported_url(image_url):
            return image_url
        return f"{base_url.rstrip('/')}/api/v1/images/proxy?url={quote(image_url, safe='')}"

    def is_proxy_url(self, image_url: str) -> bool:
        """Checks whether the URL already points at this API proxy path."""
        parsed = urlparse(image_url)
        return parsed.path.endswith("/api/v1/images/proxy")

    def is_supported_url(self, image_url: str) -> bool:
        """Checks whether this service can proxy the URL scheme."""
        parsed = urlparse(image_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def validate_public_image_url(self, image_url: str) -> str:
        """Rejects unsupported or private-network image URLs before proxying."""
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only absolute HTTP/HTTPS image URLs are supported.")

        hostname = parsed.hostname.lower()
        if hostname in self._blocked_hosts:
            raise ValueError("Private or local image URLs are not allowed.")

        try:
            ip = ipaddress.ip_address(hostname)
            if not ip.is_global:
                raise ValueError("Private or local image URLs are not allowed.")
            return parsed.geturl()
        except ValueError as e:
            if "image URLs" in str(e):
                raise

        for address in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("Private or local image URLs are not allowed.")

        return parsed.geturl()

    def _download_image(self, validated_image_url: str, verify: bool) -> requests.Response:
        """Downloads image content with the configured scraping headers."""
        response = requests.get(
            validated_image_url,
            headers={
                "User-Agent": settings.DEFAULT_USER_AGENT,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            verify=verify,
        )
        response.raise_for_status()
        return response

    def fetch_image(self, image_url: str) -> ProxiedImage:
        """Downloads an external image after validating it is safe to proxy."""
        validated_image_url = self.validate_public_image_url(image_url)
        try:
            response = self._download_image(validated_image_url, verify=settings.SSL_VERIFY)
        except SSLError:
            if not settings.SSL_VERIFY:
                raise
            response = self._download_image(validated_image_url, verify=False)

        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not media_type.startswith("image/"):
            raise ValueError("The requested URL did not return image content.")

        return ProxiedImage(content=response.content, media_type=media_type or "image/jpeg")


image_proxy_service = ImageProxyService()
