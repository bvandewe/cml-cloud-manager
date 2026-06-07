"""Tests for :class:`lcm_core.infrastructure.content_store.S3ContentClient`.

Uses ``moto[s3]`` to stand up an in-process S3-compatible backend, so the
client exercises the real boto3 code paths without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from lcm_core.infrastructure.content_store import S3ContentClient, S3ContentClientError
from moto import mock_aws


@pytest.fixture
def s3_bucket():
    """Spin up a moto-backed S3 bucket and yield (bucket_name, region)."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="lcm-content")
        client.put_object(Bucket="lcm-content", Key="packages/example.zip", Body=b"hello-zip")
        yield "lcm-content", "us-east-1"


@pytest.fixture
def s3_content_client(s3_bucket) -> S3ContentClient:
    _bucket, region = s3_bucket
    return S3ContentClient(
        endpoint_url="https://s3.amazonaws.com",
        access_key="test",
        secret_key="test",  # pragma: allowlist secret
        region=region,
        secure=True,
    )


class TestDownload:
    @pytest.mark.asyncio
    async def test_download_happy_path(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        dest = tmp_path / "example.zip"
        returned = await s3_content_client.download("s3://lcm-content/packages/example.zip", dest)
        assert returned == dest
        assert dest.read_bytes() == b"hello-zip"

    @pytest.mark.asyncio
    async def test_download_creates_parent_dirs(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        dest = tmp_path / "nested" / "deep" / "example.zip"
        await s3_content_client.download("s3://lcm-content/packages/example.zip", dest)
        assert dest.exists()

    @pytest.mark.asyncio
    async def test_download_missing_key_raises(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        with pytest.raises(S3ContentClientError) as excinfo:
            await s3_content_client.download("s3://lcm-content/packages/missing.zip", tmp_path / "x.zip")
        assert excinfo.value.bucket == "lcm-content"
        assert excinfo.value.key == "packages/missing.zip"

    @pytest.mark.asyncio
    async def test_download_missing_bucket_raises(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        with pytest.raises(S3ContentClientError) as excinfo:
            await s3_content_client.download("s3://no-such-bucket/key", tmp_path / "x.zip")
        assert excinfo.value.bucket == "no-such-bucket"


class TestHead:
    @pytest.mark.asyncio
    async def test_head_returns_size_and_etag(self, s3_content_client: S3ContentClient) -> None:
        meta = await s3_content_client.head("s3://lcm-content/packages/example.zip")
        assert meta["size"] == len(b"hello-zip")
        assert meta["etag"]
        # Quoted ETag is normalised by the client.
        assert not meta["etag"].startswith('"')

    @pytest.mark.asyncio
    async def test_head_missing_object_raises(self, s3_content_client: S3ContentClient) -> None:
        with pytest.raises(S3ContentClientError):
            await s3_content_client.head("s3://lcm-content/packages/missing.zip")


class TestUriParsing:
    @pytest.mark.asyncio
    async def test_empty_uri_raises(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        with pytest.raises(S3ContentClientError):
            await s3_content_client.download("", tmp_path / "x.zip")

    @pytest.mark.asyncio
    async def test_wrong_scheme_raises(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        with pytest.raises(S3ContentClientError) as excinfo:
            await s3_content_client.download("http://example.com/file", tmp_path / "x.zip")
        assert "scheme" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_missing_key_in_uri_raises(self, s3_content_client: S3ContentClient, tmp_path: Path) -> None:
        with pytest.raises(S3ContentClientError) as excinfo:
            await s3_content_client.download("s3://only-bucket", tmp_path / "x.zip")
        assert "malformed" in str(excinfo.value).lower()
