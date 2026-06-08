"""Unit tests for CloudEventCallbackService."""

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from application.settings import Settings
from integration.services.cloud_event_client import CloudEventCallbackService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings():
    """Test settings."""
    s = Settings()
    s.cloud_event_sink = "http://test-sink.local/events"
    s.job_progress_interval = 2  # 2s throttle
    return s


@pytest.fixture
def callback_service(settings):
    """Create a CloudEventCallbackService with test settings."""
    return CloudEventCallbackService(settings)


# ---------------------------------------------------------------------------
# URL Resolution Tests
# ---------------------------------------------------------------------------


class TestUrlResolution:
    """Tests for target URL resolution logic."""

    @pytest.mark.unit
    def test_per_job_callback_url_takes_priority(self, callback_service):
        """Per-job callback_url takes priority over global sink."""
        url = callback_service._resolve_target_url("http://job-specific.local/cb")
        assert url == "http://job-specific.local/cb"

    @pytest.mark.unit
    def test_global_sink_used_when_no_callback_url(self, callback_service):
        """Global sink is used when no per-job callback_url."""
        url = callback_service._resolve_target_url(None)
        assert url == "http://test-sink.local/events"

    @pytest.mark.unit
    def test_none_when_no_urls_configured(self):
        """Returns None when neither per-job nor global sink configured."""
        settings = Settings()
        settings.cloud_event_sink = ""
        service = CloudEventCallbackService(settings)
        url = service._resolve_target_url(None)
        assert url is None


# ---------------------------------------------------------------------------
# Retry Tests
# ---------------------------------------------------------------------------


class TestRetry:
    """Tests for retry behavior on delivery failure."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retry_on_http_error(self, callback_service):
        """Retries delivery on HTTP errors."""
        call_count = {"n": 0}

        async def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise httpx.ConnectError("Connection refused")
            response = httpx.Response(200)
            return response

        with patch.object(callback_service._client, "post", side_effect=mock_post):
            await callback_service.emit_started(
                job_id="retry-job",
                scenario_name="test",
                started_at="2026-01-01T00:00:00Z",
            )

        # Should have retried and succeeded on 3rd attempt
        assert call_count["n"] == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, callback_service):
        """Retries on 5xx responses."""
        call_count = {"n": 0}

        async def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return httpx.Response(500)
            return httpx.Response(200)

        with patch.object(callback_service._client, "post", side_effect=mock_post):
            await callback_service.emit_completed(
                job_id="retry-job-2",
                output_data={"test": True},
                artifacts=[],
                duration=1.0,
            )

        assert call_count["n"] == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_exception_raised_on_exhausted_retries(self, callback_service):
        """Fire-and-forget: no exception even after all retries exhausted."""

        async def always_fail(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch.object(callback_service._client, "post", side_effect=always_fail):
            # Should NOT raise
            await callback_service.emit_failed(
                job_id="fail-job",
                error="test error",
                duration=5.0,
            )


# ---------------------------------------------------------------------------
# Progress Throttling Tests
# ---------------------------------------------------------------------------


class TestProgressThrottling:
    """Tests for progress event throttling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_progress_throttled_within_interval(self, callback_service):
        """Progress events within interval are deduplicated."""
        post_mock = AsyncMock(return_value=httpx.Response(200))

        with patch.object(callback_service._client, "post", post_mock):
            # First call should go through
            await callback_service.emit_progress("throttle-job", 25, "First")
            # Second call within 2s interval should be throttled
            await callback_service.emit_progress("throttle-job", 50, "Second")
            await callback_service.emit_progress("throttle-job", 75, "Third")

        # Only first should be delivered (interval=2s, no time elapsed)
        assert post_mock.call_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_progress_allowed_after_interval(self, settings):
        """Progress events are allowed after the interval passes."""
        settings.job_progress_interval = 0  # No throttle
        service = CloudEventCallbackService(settings)

        post_mock = AsyncMock(return_value=httpx.Response(200))

        with patch.object(service._client, "post", post_mock):
            await service.emit_progress("no-throttle-job", 25, "First")
            await service.emit_progress("no-throttle-job", 50, "Second")

        # Both should be delivered with 0s interval
        assert post_mock.call_count == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_progress_tracking_cleaned_on_completion(self, callback_service):
        """Progress tracking is cleaned up when job completes."""
        callback_service._last_progress_time["cleanup-job"] = time.monotonic()
        callback_service._cleanup_progress_tracking("cleanup-job")
        assert "cleanup-job" not in callback_service._last_progress_time


# ---------------------------------------------------------------------------
# Metadata round-trip tests (AD-CSI-017)
# ---------------------------------------------------------------------------


class TestMetadataRoundTrip:
    """When metadata is supplied to emit_*, it must appear as ``data.metadata`` on the payload."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_emit_started_includes_metadata(self, callback_service):
        post_mock = AsyncMock(return_value=httpx.Response(200))
        with patch.object(callback_service._client, "post", post_mock):
            await callback_service.emit_started(
                job_id="job-1",
                scenario_name="lab_resolve",
                started_at="2026-01-01T00:00:00Z",
                metadata={
                    "lablet_session_id": "sess-1",
                    "step_name": "lab_resolve",
                    "step_correlation_id": "sess-1:lab_resolve:abc",
                },
            )
        assert post_mock.call_count == 1
        payload = post_mock.call_args.kwargs["json"]
        assert payload["type"] == "scenario_engine.job.started.v1"
        assert payload["data"]["metadata"] == {
            "lablet_session_id": "sess-1",
            "step_name": "lab_resolve",
            "step_correlation_id": "sess-1:lab_resolve:abc",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_emit_completed_includes_metadata(self, callback_service):
        post_mock = AsyncMock(return_value=httpx.Response(200))
        with patch.object(callback_service._client, "post", post_mock):
            await callback_service.emit_completed(
                job_id="job-2",
                output_data={"cml_lab_id": "abc"},
                artifacts=[],
                duration=2.5,
                metadata={"step_correlation_id": "sess-2:lab_start:xyz"},
            )
        payload = post_mock.call_args.kwargs["json"]
        assert payload["data"]["metadata"] == {"step_correlation_id": "sess-2:lab_start:xyz"}
        # Standard fields preserved
        assert payload["data"]["output_data"] == {"cml_lab_id": "abc"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_emit_failed_includes_metadata(self, callback_service):
        post_mock = AsyncMock(return_value=httpx.Response(200))
        with patch.object(callback_service._client, "post", post_mock):
            await callback_service.emit_failed(
                job_id="job-3",
                error="boom",
                duration=1.0,
                metadata={"step_correlation_id": "sess-3:lab_resolve:fail"},
            )
        payload = post_mock.call_args.kwargs["json"]
        assert payload["data"]["metadata"] == {"step_correlation_id": "sess-3:lab_resolve:fail"}
        assert payload["data"]["error"] == "boom"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_emit_without_metadata_omits_key(self, callback_service):
        """Backward-compat: when metadata=None, ``data.metadata`` key is absent."""
        post_mock = AsyncMock(return_value=httpx.Response(200))
        with patch.object(callback_service._client, "post", post_mock):
            await callback_service.emit_started(
                job_id="job-no-meta",
                scenario_name="lab_resolve",
                started_at="2026-01-01T00:00:00Z",
            )
        payload = post_mock.call_args.kwargs["json"]
        assert "metadata" not in payload["data"]
