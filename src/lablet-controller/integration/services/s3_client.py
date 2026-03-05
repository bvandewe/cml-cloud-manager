"""S3-compatible object storage client for RustFS/MinIO.

Provides bucket and object management operations used by the
ContentSyncService to upload content packages to RustFS.

Uses boto3 with S3-compatible endpoint configuration.
Synchronous boto3 calls wrapped in async interface for consistency
with the rest of the codebase.

AD-CS-002: Package uploaded as-is (zip archive) to slugified-FQN bucket.
"""

import logging
from io import BytesIO
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


class S3ClientError(Exception):
    """Base exception for S3 client errors."""

    def __init__(self, message: str, bucket: str | None = None, key: str | None = None) -> None:
        super().__init__(message)
        self.bucket = bucket
        self.key = key


class S3Client:
    """S3-compatible storage client for RustFS/MinIO.

    Provides async-style methods for bucket and object management.
    boto3 operations are synchronous but lightweight — the actual
    data transfer is the bottleneck, not the API call overhead.

    Configuration:
        S3_ENDPOINT: RustFS/MinIO endpoint URL
        S3_ACCESS_KEY: Access key ID
        S3_SECRET_KEY: Secret access key
        S3_REGION: AWS region (default: us-east-1)
        S3_SECURE: Use HTTPS (default: false)
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        secure: bool = False,
    ) -> None:
        """Initialize S3 client.

        Args:
            endpoint_url: S3-compatible endpoint URL.
            access_key: Access key ID.
            secret_key: Secret access key.
            region: AWS region name.
            secure: Use HTTPS (modifies endpoint if needed).
        """
        self._endpoint_url = endpoint_url
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
        logger.info(f"S3Client initialized (endpoint={endpoint_url}, region={region})")

    async def ensure_bucket_exists(self, bucket_name: str) -> None:
        """Create bucket if it doesn't exist.

        Args:
            bucket_name: S3 bucket name (must be valid S3 name).

        Raises:
            S3ClientError: On unexpected S3 errors.
        """
        try:
            self._client.head_bucket(Bucket=bucket_name)
            logger.debug(f"Bucket '{bucket_name}' already exists")
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                try:
                    self._client.create_bucket(Bucket=bucket_name)
                    logger.info(f"Created bucket '{bucket_name}'")
                except ClientError as create_err:
                    raise S3ClientError(f"Failed to create bucket '{bucket_name}': {create_err}", bucket=bucket_name) from create_err
            else:
                raise S3ClientError(f"Failed to check bucket '{bucket_name}': {e}", bucket=bucket_name) from e

    async def upload_bytes(
        self,
        bucket_name: str,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes to S3.

        Args:
            bucket_name: Target bucket name.
            object_key: Object key (filename) in the bucket.
            data: Raw bytes to upload.
            content_type: MIME content type.

        Returns:
            The S3 URI of the uploaded object (s3://bucket/key).

        Raises:
            S3ClientError: On upload failure.
        """
        try:
            self._client.upload_fileobj(
                BytesIO(data),
                bucket_name,
                object_key,
                ExtraArgs={"ContentType": content_type},
            )
            uri = f"s3://{bucket_name}/{object_key}"
            logger.info(f"Uploaded {len(data)} bytes to {uri}")
            return uri
        except ClientError as e:
            raise S3ClientError(f"Failed to upload to s3://{bucket_name}/{object_key}: {e}", bucket=bucket_name, key=object_key) from e

    async def object_exists(self, bucket_name: str, object_key: str) -> bool:
        """Check if an object exists in a bucket.

        Args:
            bucket_name: Bucket name.
            object_key: Object key.

        Returns:
            True if the object exists, False otherwise.
        """
        try:
            self._client.head_object(Bucket=bucket_name, Key=object_key)
            return True
        except ClientError:
            return False

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        secure: bool = False,
    ) -> None:
        """Register S3Client as singleton in DI container.

        Args:
            services: Neuroglia service collection.
            endpoint_url: S3-compatible endpoint URL.
            access_key: S3 access key.
            secret_key: S3 secret key.
            region: AWS region.
            secure: Use HTTPS.
        """

        def factory(sp: "ServiceProviderBase") -> "S3Client":
            return cls(
                endpoint_url=endpoint_url,
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                secure=secure,
            )

        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        logger.info(f"✅ S3Client configured (endpoint={endpoint_url})")
