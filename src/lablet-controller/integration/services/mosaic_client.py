"""Mosaic content authoring platform client.

Provides methods to:
1. Get latest publish records for a form qualified name
2. Download content packages (zip archives)

The Mosaic base URL is resolved dynamically via the Environment Resolver
(MOSAIC_BASE_URL from resolver response). The base_url is NOT configured
statically — it must be passed per-call after resolution.

Authentication: OAuth2 client credentials via Keycloak.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from integration.services.oauth2_token_manager import OAuth2TokenManager, TokenConfig

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


class MosaicClientError(Exception):
    """Error from the Mosaic API."""

    def __init__(self, message: str, status_code: int | None = None, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


@dataclass
class PublishRecord:
    """Represents a Mosaic publish record.

    Each record corresponds to a published package for a specific
    form qualified name and layout type (e.g., LDSv3).
    """

    id: str  # publishedRecordId (24-char hex)
    form_name: str
    layout: str
    version: str
    date_published: str
    raw_data: dict[str, Any]  # Full response for extensibility


class MosaicClient:
    """Client for the Mosaic content authoring platform API.

    Retrieves publish records and downloads content packages (zip archives)
    from Mosaic instances. The Mosaic base URL varies by form/environment
    and must be resolved via EnvironmentResolverClient before each call.

    Authentication: OAuth2 client credentials via Keycloak (optional).

    Configuration:
        MOSAIC_TOKEN_URL: Keycloak token endpoint
        MOSAIC_CLIENT_ID: OAuth2 client ID
        MOSAIC_CLIENT_SECRET: OAuth2 client secret
        MOSAIC_SCOPES: Space-separated scopes
    """

    def __init__(self, token_manager: OAuth2TokenManager | None = None) -> None:
        """Initialize Mosaic client.

        Args:
            token_manager: Optional OAuth2 token manager for authentication.
        """
        self._token_manager = token_manager
        self._http = httpx.AsyncClient(verify=False, timeout=120.0)  # Large downloads need longer timeout

    async def _get_auth_headers(self) -> dict[str, str]:
        """Get auth headers (Bearer token from client credentials)."""
        if self._token_manager:
            return await self._token_manager.get_auth_headers()
        return {}

    async def get_latest_publish_records(
        self,
        mosaic_base_url: str,
        qualified_name: str,
    ) -> list[PublishRecord]:
        """Get latest publish records for all packages given a qualified name.

        Calls: GET {mosaic_base_url}/api/v1/latest/publishrecords?qualifiedName={fqn}

        Args:
            mosaic_base_url: Mosaic instance base URL (from Environment Resolver).
            qualified_name: The form qualified name.

        Returns:
            List of PublishRecord objects (one per layout/package type).

        Raises:
            MosaicClientError: On non-2xx response.
        """
        headers = await self._get_auth_headers()
        headers["Accept"] = "application/json"

        url = f"{mosaic_base_url.rstrip('/')}/api/v1/latest/publishrecords"
        logger.info(f"Fetching publish records for FQN='{qualified_name}' from {url}")

        try:
            response = await self._http.get(
                url,
                params={"qualifiedName": qualified_name},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MosaicClientError(
                f"Failed to get publish records for '{qualified_name}': {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e

        data = response.json()

        # Debug: log raw response structure to diagnose field mapping issues
        if isinstance(data, dict):
            logger.debug(f"Raw Mosaic response type=dict, keys={list(data.keys())}")
            for k, v in data.items():
                if isinstance(v, list) and v:
                    logger.debug(f"  layout '{k}': {len(v)} records, first record keys={list(v[0].keys()) if isinstance(v[0], dict) else 'N/A'}")
                    logger.debug(f"  layout '{k}': first record={v[0]}")
        elif isinstance(data, list):
            logger.debug(f"Raw Mosaic response type=list, length={len(data)}")
            if data and isinstance(data[0], dict):
                logger.debug(f"  first record keys={list(data[0].keys())}")
                logger.debug(f"  first record={data[0]}")

        # Response may be a dict keyed by layout type, or a flat list
        records: list[PublishRecord] = []
        if isinstance(data, dict):
            for layout_key, layout_records in data.items():
                if isinstance(layout_records, list):
                    for rec in layout_records:
                        records.append(self._parse_publish_record(rec, layout_key))
        elif isinstance(data, list):
            for rec in data:
                records.append(self._parse_publish_record(rec, ""))

        logger.info(f"Found {len(records)} publish records for '{qualified_name}'")
        return records

    async def download_package(
        self,
        mosaic_base_url: str,
        published_record_id: str,
    ) -> bytes:
        """Download a content package (zip archive) by published record ID.

        Calls: GET {mosaic_base_url}/api/file/download/package/{publishedRecordId}

        Note: The legacy /api/v1/download/export_package/ endpoint returns 200
        with empty body. The correct endpoint (observed from Mosaic UI network
        traffic) is /api/file/download/package/{id}.

        Args:
            mosaic_base_url: Mosaic instance base URL.
            published_record_id: The 24-char hex ID of the publish record.

        Returns:
            Raw bytes of the zip archive.

        Raises:
            MosaicClientError: On non-2xx response or empty content.
        """
        if not published_record_id:
            raise MosaicClientError(
                "Cannot download package: published_record_id is empty. "
                "The publish record was likely parsed with a missing ID field. "
                "Check _parse_publish_record field mapping against the Mosaic API response.",
                status_code=None,
            )

        headers = await self._get_auth_headers()
        url = f"{mosaic_base_url.rstrip('/')}/api/file/download/package/{published_record_id}"
        logger.info(f"Downloading package {published_record_id} from {url}")

        try:
            response = await self._http.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MosaicClientError(
                f"Failed to download package {published_record_id}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e

        # Debug: log response metadata to diagnose empty-body issues
        content_type = response.headers.get("content-type", "N/A")
        content_length = response.headers.get("content-length", "N/A")
        logger.debug(
            f"Download response: status={response.status_code}, "
            f"content-type={content_type}, content-length={content_length}, "
            f"actual_bytes={len(response.content)}, "
            f"history={[r.status_code for r in response.history] if response.history else 'no redirects'}, "
            f"final_url={response.url}"
        )

        content = response.content
        if not content:
            # Log response headers + first 500 chars of text body for diagnosis
            text_preview = response.text[:500] if response.text else "(empty)"
            logger.error(f"Empty package body for record {published_record_id}. Headers: {dict(response.headers)}. Text preview: {text_preview}")
            raise MosaicClientError(
                f"Empty package downloaded for record {published_record_id} (status={response.status_code}, content-type={content_type})",
                status_code=response.status_code,
            )

        logger.info(f"Downloaded package: {len(content)} bytes")
        return content

    @staticmethod
    def _parse_publish_record(rec: dict[str, Any], default_layout: str) -> PublishRecord:
        """Parse a raw API response dict into a PublishRecord.

        Args:
            rec: Raw record dict from Mosaic API.
            default_layout: Fallback layout if not in record.

        Returns:
            Parsed PublishRecord.
        """
        record_id = rec.get("publishRecordId", rec.get("_id", rec.get("id", "")))
        form_name = rec.get("mosaicPkgName", rec.get("formName", ""))
        version = str(rec.get("versionNumber", rec.get("version", "")))
        date_published = rec.get("createdAt", rec.get("datePublished", ""))

        if not record_id:
            logger.warning(f"PublishRecord has no ID! Available keys: {list(rec.keys())}, raw={rec}")
        else:
            logger.debug(f"Parsed PublishRecord: id={record_id}, form={form_name}, version={version}")

        return PublishRecord(
            id=record_id,
            form_name=form_name,
            layout=rec.get("layoutName", rec.get("layout", default_layout)),
            version=version,
            date_published=date_published,
            raw_data=rec,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
        if self._token_manager:
            await self._token_manager.close()

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        token_config: TokenConfig | None = None,
    ) -> None:
        """Register MosaicClient as singleton in DI container.

        Args:
            services: Neuroglia service collection.
            token_config: Optional OAuth2 client credentials config.
        """

        def factory(sp: "ServiceProviderBase") -> "MosaicClient":
            token_manager = None
            if token_config and token_config.token_url:
                token_manager = OAuth2TokenManager(token_config)
            return cls(token_manager=token_manager)

        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        logger.info("✅ MosaicClient configured")
