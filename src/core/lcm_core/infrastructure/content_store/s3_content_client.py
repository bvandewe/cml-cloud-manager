"""S3-compatible content client for the PAv1 content store.

Thin async wrapper around ``boto3`` for downloading PAv1 packages from
RustFS / MinIO / S3. Mirrors the pattern used by
``src/lablet-controller/integration/services/s3_client.py`` but lives in
``lcm_core`` so the Scenario Engine (and any future consumer) depends only
on ``lcm_core`` + ``boto3`` for content retrieval.

Public surface:

- :class:`S3ContentClient` — async-wrapped download/head against ``s3://bucket/key`` URIs.
- :class:`S3ContentClientError` — base exception with ``uri`` / ``bucket`` / ``key`` context.

See CPA↔SE integration plan §3 G-01.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class S3ContentClientError(Exception):
    """Base exception for :class:`S3ContentClient` failures.

    Carries the offending URI (and its parsed bucket/key when available) so
    callers can produce diagnostic messages without re-parsing.
    """

    def __init__(
        self,
        message: str,
        *,
        uri: str | None = None,
        bucket: str | None = None,
        key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.uri = uri
        self.bucket = bucket
        self.key = key


class S3ContentClient:
    """S3-compatible content client used by ``ContentExtractor`` / ``SyncContentCommand``.

    Synchronous ``boto3`` calls are wrapped in :func:`asyncio.to_thread` so the
    surface is async-compatible with the rest of the scenario-engine runtime.
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        secure: bool = True,
    ) -> None:
        """Initialise the underlying ``boto3`` client.

        Args:
            endpoint_url: S3-compatible endpoint URL (e.g. ``http://aix-rustfs:9000``).
            access_key: Access key ID.
            secret_key: Secret access key.
            region: AWS region name (defaults to ``us-east-1`` for RustFS/MinIO).
            secure: Reserved for forwards compat; the endpoint scheme drives TLS today.
        """
        self._endpoint_url = endpoint_url
        self._secure = secure
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )
        logger.info("S3ContentClient initialised (endpoint=%s, region=%s)", endpoint_url, region)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download(self, uri: str, dest_path: Path) -> Path:
        """Download an object at ``uri`` to ``dest_path``.

        Args:
            uri: An ``s3://bucket/key`` URI.
            dest_path: Local filesystem destination. Parent directories are
                created if missing.

        Returns:
            The destination path on success.

        Raises:
            S3ContentClientError: On malformed URI, missing object/bucket, or
                any underlying ``boto3`` / OS error.
        """
        bucket, key = _parse_s3_uri(uri)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        def _do_download() -> None:
            try:
                self._client.download_file(bucket, key, str(dest_path))
            except (ClientError, BotoCoreError, OSError) as exc:
                raise S3ContentClientError(
                    f"S3 download failed for {uri}: {exc}",
                    uri=uri,
                    bucket=bucket,
                    key=key,
                ) from exc

        await asyncio.to_thread(_do_download)
        logger.info("Downloaded %s → %s", uri, dest_path)
        return dest_path

    async def head(self, uri: str) -> dict[str, Any]:
        """Return basic object metadata (``size``, ``etag``) for ``uri``.

        Args:
            uri: An ``s3://bucket/key`` URI.

        Raises:
            S3ContentClientError: On malformed URI, missing object/bucket, or
                any underlying ``boto3`` error.
        """
        bucket, key = _parse_s3_uri(uri)

        def _do_head() -> dict[str, Any]:
            try:
                response = self._client.head_object(Bucket=bucket, Key=key)
            except (ClientError, BotoCoreError) as exc:
                raise S3ContentClientError(
                    f"S3 head failed for {uri}: {exc}",
                    uri=uri,
                    bucket=bucket,
                    key=key,
                ) from exc
            return {
                "size": int(response.get("ContentLength", 0)),
                "etag": (response.get("ETag") or "").strip('"'),
                "content_type": response.get("ContentType"),
            }

        return await asyncio.to_thread(_do_head)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse ``s3://bucket/key`` → ``(bucket, key)``.

    Raises:
        S3ContentClientError: If the URI is empty, has the wrong scheme, or
            does not include a key path.
    """
    if not uri:
        raise S3ContentClientError("S3 URI must not be empty", uri=uri)

    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise S3ContentClientError(
            f"Unsupported URI scheme '{parsed.scheme}' (expected 's3')",
            uri=uri,
        )
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise S3ContentClientError(
            f"Malformed S3 URI '{uri}': require both bucket and key",
            uri=uri,
            bucket=bucket or None,
            key=key or None,
        )
    return bucket, key
