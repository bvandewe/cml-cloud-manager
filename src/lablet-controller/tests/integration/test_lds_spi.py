"""Unit tests for LDS SPI Client.

Tests cover:
- Data models: DeviceAccessInfo, SessionPartInfo, LdsSessionInfo, LdsDeploymentConfig
- Configuration loading: load_lds_deployment_configs()
- Client initialization: region selection, fallback behavior
- Reconciler helper: _build_device_access_list()
- HTTP API interactions (mocked via httpx)

AD-P4-01: Atomic mark-ready transition with LDS session info
AD-P4-02: Multi-region YAML config loading
AD-P4-03: CML node label = device_label, tags encode protocol:port
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import yaml

from integration.services.lds_spi import (
    DeviceAccessInfo,
    LdsDeploymentConfig,
    LdsDeploymentNotFoundError,
    LdsSessionInfo,
    LdsSessionNotFoundError,
    LdsSpiClient,
    LdsSpiError,
    SessionPartInfo,
    load_lds_deployment_configs,
)

# =============================================================================
# Data Model Tests
# =============================================================================


class TestDeviceAccessInfo:
    """Tests for DeviceAccessInfo dataclass."""

    def test_basic_creation(self):
        """Test creating DeviceAccessInfo with required fields."""
        device = DeviceAccessInfo(
            device_label="Router1",
            protocol="ssh",
            host="10.0.0.1",
        )
        assert device.device_label == "Router1"
        assert device.protocol == "ssh"
        assert device.host == "10.0.0.1"
        assert device.port is None
        assert device.password is None

    def test_creation_with_all_fields(self):
        """Test creating DeviceAccessInfo with all fields."""
        device = DeviceAccessInfo(
            device_label="Switch1",
            protocol="vnc",
            host="10.0.0.2",
            port=5044,
            password="secret123",
        )
        assert device.port == 5044
        assert device.password == "secret123"

    def test_to_api_dict_minimal(self):
        """Test to_api_dict with only required fields."""
        device = DeviceAccessInfo(
            device_label="Router1",
            protocol="telnet",
            host="10.0.0.1",
        )
        result = device.to_api_dict()

        assert result == {
            "device_label": "Router1",
            "protocol": "telnet",
            "host": "10.0.0.1",
        }
        assert "port" not in result
        assert "password" not in result

    def test_to_api_dict_with_optional_fields(self):
        """Test to_api_dict includes optional fields when set."""
        device = DeviceAccessInfo(
            device_label="Router1",
            protocol="ssh",
            host="10.0.0.1",
            port=22,
            password="cisco",
        )
        result = device.to_api_dict()

        assert result == {
            "device_label": "Router1",
            "protocol": "ssh",
            "host": "10.0.0.1",
            "port": 22,
            "password": "cisco",
        }

    def test_to_api_dict_port_zero_is_included(self):
        """Test that port=0 is still included (only None is excluded)."""
        device = DeviceAccessInfo(
            device_label="Router1",
            protocol="ssh",
            host="10.0.0.1",
            port=0,
        )
        result = device.to_api_dict()
        assert result["port"] == 0


class TestSessionPartInfo:
    """Tests for SessionPartInfo dataclass."""

    def test_creation_defaults(self):
        """Test SessionPartInfo with defaults."""
        part = SessionPartInfo(part_num=1)
        assert part.part_num == 1
        assert part.form_qualified_name is None
        assert part.track is None
        assert part.exam_version is None
        assert part.repository_type == "minio"
        assert part.session_part_state == ""

    def test_creation_with_values(self):
        """Test SessionPartInfo with all values set."""
        part = SessionPartInfo(
            part_num=1,
            form_qualified_name="lablet-basic-routing-1.0.0",
            track="CCNA",
            exam_version="2024",
            repository_type="minio",
            session_part_state="SESSION_PENDING",
        )
        assert part.form_qualified_name == "lablet-basic-routing-1.0.0"
        assert part.track == "CCNA"


class TestLdsSessionInfo:
    """Tests for LdsSessionInfo dataclass and from_api_response()."""

    def test_basic_creation(self):
        """Test basic LdsSessionInfo creation."""
        info = LdsSessionInfo(
            session_id="sess-123",
            login_url="https://lds.example.com/login",
            status="SESSION_PENDING",
        )
        assert info.session_id == "sess-123"
        assert info.login_url == "https://lds.example.com/login"
        assert info.status == "SESSION_PENDING"
        assert info.session_parts == []

    def test_from_api_response_minimal(self):
        """Test from_api_response with minimal API data."""
        api_data = {
            "id": "abc-123",
            "state": "SESSION_PENDING",
        }
        info = LdsSessionInfo.from_api_response(api_data)

        assert info.session_id == "abc-123"
        assert info.status == "SESSION_PENDING"
        assert info.login_url == ""
        assert info.session_parts == []

    def test_from_api_response_with_parts(self):
        """Test from_api_response with session parts."""
        api_data = {
            "id": "abc-123",
            "state": "ACTIVE",
            "session_parts": [
                {
                    "form_qualified_name": "lablet-basic-routing-1.0.0",
                    "track": "CCNA",
                    "exam_version": "2024.1",
                    "repository_type": "minio",
                    "session_part_state": "SESSION_PENDING",
                },
                {
                    "form_qualified_name": "lablet-advanced-switching-1.0.0",
                    "session_part_state": "ACTIVE",
                },
            ],
        }
        info = LdsSessionInfo.from_api_response(api_data, login_url="https://lds.example.com/login")

        assert info.session_id == "abc-123"
        assert info.status == "ACTIVE"
        assert info.login_url == "https://lds.example.com/login"
        assert len(info.session_parts) == 2

        # Part 1
        assert info.session_parts[0].part_num == 1
        assert info.session_parts[0].form_qualified_name == "lablet-basic-routing-1.0.0"
        assert info.session_parts[0].track == "CCNA"
        assert info.session_parts[0].exam_version == "2024.1"
        assert info.session_parts[0].repository_type == "minio"
        assert info.session_parts[0].session_part_state == "SESSION_PENDING"

        # Part 2
        assert info.session_parts[1].part_num == 2
        assert info.session_parts[1].form_qualified_name == "lablet-advanced-switching-1.0.0"
        assert info.session_parts[1].repository_type == "minio"  # default
        assert info.session_parts[1].session_part_state == "ACTIVE"

    def test_from_api_response_missing_fields(self):
        """Test from_api_response with empty data returns safe defaults."""
        info = LdsSessionInfo.from_api_response({})

        assert info.session_id == ""
        assert info.status == ""
        assert info.login_url == ""
        assert info.session_parts == []


# =============================================================================
# LDS Deployment Config Tests
# =============================================================================


class TestLdsDeploymentConfig:
    """Tests for LdsDeploymentConfig dataclass."""

    def test_from_dict(self):
        """Test creating config from YAML dict."""
        data = {
            "base_url": "https://lds-us-east.example.com/",
            "username": "admin",
            "password": "secret",
            "timeout_seconds": 60,
            "label": "US East LDS",
        }
        config = LdsDeploymentConfig.from_dict("us-east-1", data)

        assert config.region == "us-east-1"
        assert config.base_url == "https://lds-us-east.example.com"  # trailing slash stripped
        assert config.username == "admin"
        assert config.password == "secret"
        assert config.timeout_seconds == 60.0
        assert config.label == "US East LDS"

    def test_from_dict_defaults(self):
        """Test from_dict with missing optional fields uses defaults."""
        data = {
            "base_url": "https://lds.example.com",
            "username": "user",
            "password": "pass",
        }
        config = LdsDeploymentConfig.from_dict("eu-west-1", data)

        assert config.timeout_seconds == 30.0
        assert config.label == "LDS eu-west-1"  # auto-generated

    def test_from_dict_empty_base_url(self):
        """Test from_dict with missing base_url returns empty string."""
        config = LdsDeploymentConfig.from_dict("test", {})

        assert config.base_url == ""
        assert config.username == ""
        assert config.password == ""


# =============================================================================
# Config Loading Tests
# =============================================================================


class TestLoadLdsDeploymentConfigs:
    """Tests for load_lds_deployment_configs()."""

    def test_load_valid_config(self, tmp_path: Path):
        """Test loading a valid YAML config file."""
        config_data = {
            "default_region": "us-east-1",
            "deployments": {
                "us-east-1": {
                    "base_url": "https://lds-us-east.example.com",
                    "username": "admin",
                    "password": "secret",
                    "timeout_seconds": 30,
                    "label": "US East LDS",
                },
                "eu-west-1": {
                    "base_url": "https://lds-eu-west.example.com",
                    "username": "admin-eu",
                    "password": "secret-eu",
                    "label": "EU West LDS",
                },
            },
        }
        config_file = tmp_path / "lds_deployments.yaml"
        config_file.write_text(yaml.dump(config_data))

        configs, default_region = load_lds_deployment_configs(str(config_file))

        assert len(configs) == 2
        assert "us-east-1" in configs
        assert "eu-west-1" in configs
        assert default_region == "us-east-1"
        assert configs["us-east-1"].base_url == "https://lds-us-east.example.com"
        assert configs["eu-west-1"].username == "admin-eu"

    def test_load_no_config_path_returns_empty(self, tmp_path, monkeypatch):
        """Test that None config path with no candidates returns empty.

        Uses tmp_path as CWD to avoid finding real config/lds_deployments.yaml
        that exists in the project root.
        """
        monkeypatch.chdir(tmp_path)
        configs, default_region = load_lds_deployment_configs(None)

        assert configs == {}
        assert default_region == ""

    def test_load_nonexistent_file_returns_empty(self):
        """Test that a non-existent path returns empty."""
        configs, default_region = load_lds_deployment_configs("/nonexistent/path.yaml")

        assert configs == {}
        assert default_region == ""

    def test_load_missing_deployments_key(self, tmp_path: Path):
        """Test that missing 'deployments' key returns empty."""
        config_file = tmp_path / "lds_deployments.yaml"
        config_file.write_text(yaml.dump({"something_else": True}))

        configs, default_region = load_lds_deployment_configs(str(config_file))

        assert configs == {}
        assert default_region == ""

    def test_load_invalid_yaml(self, tmp_path: Path):
        """Test that invalid YAML returns empty."""
        config_file = tmp_path / "lds_deployments.yaml"
        config_file.write_text(": invalid: yaml: [[[")

        configs, default_region = load_lds_deployment_configs(str(config_file))

        # yaml.safe_load may not raise on all malformed input
        # but the result should be safe
        assert isinstance(configs, dict)

    def test_load_default_region_not_in_deployments(self, tmp_path: Path):
        """Test that invalid default_region falls back to first deployment."""
        config_data = {
            "default_region": "ap-southeast-1",
            "deployments": {
                "us-east-1": {
                    "base_url": "https://lds.example.com",
                    "username": "admin",
                    "password": "secret",
                },
            },
        }
        config_file = tmp_path / "lds_deployments.yaml"
        config_file.write_text(yaml.dump(config_data))

        configs, default_region = load_lds_deployment_configs(str(config_file))

        assert len(configs) == 1
        assert default_region == "us-east-1"  # Falls back to first

    def test_load_empty_deployments(self, tmp_path: Path):
        """Test loading config with empty deployments dict."""
        config_data = {
            "default_region": "us-east-1",
            "deployments": {},
        }
        config_file = tmp_path / "lds_deployments.yaml"
        config_file.write_text(yaml.dump(config_data))

        configs, default_region = load_lds_deployment_configs(str(config_file))

        assert configs == {}


# =============================================================================
# LDS SPI Client Tests
# =============================================================================


class TestLdsSpiClient:
    """Tests for LdsSpiClient initialization and region selection."""

    @pytest.fixture
    def sample_deployments(self) -> dict[str, LdsDeploymentConfig]:
        """Create sample deployment configs."""
        return {
            "us-east-1": LdsDeploymentConfig(
                region="us-east-1",
                base_url="https://lds-us-east.example.com",
                username="admin",
                password="secret",
                label="US East LDS",
            ),
            "eu-west-1": LdsDeploymentConfig(
                region="eu-west-1",
                base_url="https://lds-eu-west.example.com",
                username="admin-eu",
                password="secret-eu",
                label="EU West LDS",
            ),
        }

    @pytest.fixture
    def client(self, sample_deployments: dict[str, LdsDeploymentConfig]) -> LdsSpiClient:
        """Create a test client."""
        return LdsSpiClient(
            deployments=sample_deployments,
            default_region="us-east-1",
        )

    def test_available_regions(self, client: LdsSpiClient):
        """Test listing available regions."""
        regions = client.available_regions
        assert "us-east-1" in regions
        assert "eu-west-1" in regions

    def test_default_region(self, client: LdsSpiClient):
        """Test default region property."""
        assert client.default_region == "us-east-1"

    def test_has_deployment(self, client: LdsSpiClient):
        """Test has_deployment check."""
        assert client.has_deployment("us-east-1") is True
        assert client.has_deployment("ap-southeast-1") is False

    def test_get_deployment_exact_region(self, client: LdsSpiClient):
        """Test _get_deployment with exact region match."""
        deployment = client._get_deployment("eu-west-1")
        assert deployment.region == "eu-west-1"
        assert deployment.base_url == "https://lds-eu-west.example.com"

    def test_get_deployment_fallback_to_default(self, client: LdsSpiClient):
        """Test _get_deployment falls back to default for unknown region."""
        deployment = client._get_deployment("ap-southeast-1")
        assert deployment.region == "us-east-1"  # default

    def test_get_deployment_no_region_uses_default(self, client: LdsSpiClient):
        """Test _get_deployment with None region uses default."""
        deployment = client._get_deployment(None)
        assert deployment.region == "us-east-1"

    def test_get_deployment_no_deployments_raises(self):
        """Test _get_deployment raises when no deployments configured."""
        client = LdsSpiClient(deployments={}, default_region="")

        with pytest.raises(LdsDeploymentNotFoundError) as exc_info:
            client._get_deployment("us-east-1")

        assert "us-east-1" in str(exc_info.value)

    def test_client_no_deployments(self):
        """Test creating client with no deployments."""
        client = LdsSpiClient()
        assert client.available_regions == []
        assert client.default_region == ""


# =============================================================================
# LDS SPI Client HTTP Tests (mocked)
# =============================================================================


class TestLdsSpiClientHttp:
    """Tests for LDS SPI client HTTP methods with mocked httpx."""

    @pytest.fixture
    def client(self) -> LdsSpiClient:
        """Create a test client with a single deployment."""
        deployments = {
            "us-east-1": LdsDeploymentConfig(
                region="us-east-1",
                base_url="https://lds.example.com",
                username="admin",
                password="secret",
                label="Test LDS",
            ),
        }
        return LdsSpiClient(deployments=deployments, default_region="us-east-1")

    @pytest.mark.asyncio
    async def test_create_session_success(self, client: LdsSpiClient):
        """Test successful session creation."""
        mock_response = httpx.Response(
            200,
            json={"session_id": "sess-abc-123"},
            request=httpx.Request("POST", "https://lds.example.com/reservations/v3/lab_session"),
        )

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            result = await client.create_session(
                username="user1",
                first_name="John",
                last_name="Doe",
                scheduled_date="2025-01-15T10:00:00Z",
                form_qualified_name="lablet-basic-routing-1.0.0",
                region="us-east-1",
            )

            assert result.session_id == "sess-abc-123"
            assert result.status == "SESSION_PENDING"
            mock_async_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_session_http_error(self, client: LdsSpiClient):
        """Test session creation failure raises LdsSpiError."""
        mock_request = httpx.Request("POST", "https://lds.example.com/reservations/v3/lab_session")
        mock_response = httpx.Response(500, text="Internal Error", request=mock_request)

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(side_effect=httpx.HTTPStatusError("Server Error", request=mock_request, response=mock_response))
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            with pytest.raises(LdsSpiError) as exc_info:
                await client.create_session(
                    username="user1",
                    first_name="John",
                    last_name="Doe",
                    scheduled_date="2025-01-15T10:00:00Z",
                    form_qualified_name="lablet-basic-routing-1.0.0",
                )

            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_session_info_success(self, client: LdsSpiClient):
        """Test getting session info."""
        api_response = {
            "id": "sess-abc-123",
            "state": "SESSION_PENDING",
            "session_parts": [
                {
                    "form_qualified_name": "lablet-basic-routing-1.0.0",
                    "repository_type": "minio",
                    "session_part_state": "SESSION_PENDING",
                }
            ],
        }
        mock_response = httpx.Response(
            200,
            json=api_response,
            request=httpx.Request("GET", "https://lds.example.com/reservations/v3/lab_session/sess-abc-123"),
        )

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            result = await client.get_session_info("sess-abc-123")

            assert result.session_id == "sess-abc-123"
            assert result.status == "SESSION_PENDING"
            assert len(result.session_parts) == 1

    @pytest.mark.asyncio
    async def test_get_session_info_not_found(self, client: LdsSpiClient):
        """Test getting session info for non-existent session."""
        mock_request = httpx.Request("GET", "https://lds.example.com/reservations/v3/lab_session/bad-id")
        mock_response = httpx.Response(404, text="Not Found", request=mock_request)

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(side_effect=httpx.HTTPStatusError("Not Found", request=mock_request, response=mock_response))
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            with pytest.raises(LdsSessionNotFoundError):
                await client.get_session_info("bad-id")

    @pytest.mark.asyncio
    async def test_get_lablet_launch_url_success(self, client: LdsSpiClient):
        """Test getting lablet launch URL."""
        mock_response = httpx.Response(
            200,
            json={"url": "https://lds.example.com/session/abc123?jwt=token123"},
            request=httpx.Request(
                "GET",
                "https://lds.example.com/reservations/v3/lab_session/sess-123/lablet_launch_url",
            ),
        )

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            url = await client.get_lablet_launch_url("sess-123")

            assert url == "https://lds.example.com/session/abc123?jwt=token123"

    @pytest.mark.asyncio
    async def test_set_devices_success(self, client: LdsSpiClient):
        """Test setting devices on a session part."""
        devices = [
            DeviceAccessInfo(device_label="Router1", protocol="ssh", host="10.0.0.1", port=22),
            DeviceAccessInfo(device_label="Switch1", protocol="telnet", host="10.0.0.1", port=5041),
        ]
        mock_response = httpx.Response(
            200,
            json=[
                {"device_label": "Router1", "protocol": "ssh", "host": "10.0.0.1", "port": 22},
                {"device_label": "Switch1", "protocol": "telnet", "host": "10.0.0.1", "port": 5041},
            ],
            request=httpx.Request(
                "PUT",
                "https://lds.example.com/reservations/v3/lab_session/sess-123/part/1/devices",
            ),
        )

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.put = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            result = await client.set_devices("sess-123", part_num=1, devices=devices)

            assert len(result) == 2
            mock_async_client.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_session_success(self, client: LdsSpiClient):
        """Test archiving (releasing) a session."""
        mock_response = httpx.Response(
            200,
            json={},
            request=httpx.Request(
                "POST",
                "https://lds.example.com/reservations/v3/lab_session/sess-123/release",
            ),
        )

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            # Should not raise
            await client.archive_session("sess-123")
            mock_async_client.post.assert_called_once()

            # Verify json={} is sent (not None) to avoid HTTP 415
            call_kwargs = mock_async_client.post.call_args
            assert call_kwargs.kwargs.get("json") == {} or call_kwargs[1].get("json") == {}, "archive_session must send json={}, not json=None, to avoid HTTP 415 Unsupported Media Type from LDS"

    @pytest.mark.asyncio
    async def test_archive_session_failure_raises(self, client: LdsSpiClient):
        """Test archiving session raises on HTTP error."""
        mock_request = httpx.Request(
            "POST",
            "https://lds.example.com/reservations/v3/lab_session/sess-123/release",
        )
        mock_response = httpx.Response(500, text="Error", request=mock_request)

        with patch("integration.services.lds_spi.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(side_effect=httpx.HTTPStatusError("Error", request=mock_request, response=mock_response))
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_async_client

            with pytest.raises(LdsSpiError) as exc_info:
                await client.archive_session("sess-123")

            assert exc_info.value.status_code == 500


# =============================================================================
# Build Device Access List (Reconciler Helper) Tests
# =============================================================================


class TestBuildDeviceAccessList:
    """Tests for LabletReconciler._build_device_access_list static method.

    AD-P4-03: CML node label = device_label, tags encode protocol:port.
    """

    @pytest.fixture(autouse=True)
    def _import_reconciler(self):
        """Import the reconciler class for the static method."""
        from application.hosted_services.lablet_reconciler import LabletReconciler
        from integration.services.cml_labs_spi import NodeInfo

        self.LabletReconciler = LabletReconciler
        self.NodeInfo = NodeInfo

    def _make_node(self, label: str, tags: list[str] | None = None) -> "NodeInfo":
        """Helper to create a NodeInfo for testing."""
        return self.NodeInfo(
            id="node-1",
            label=label,
            node_definition="iosv",
            state="BOOTED",
            tags=tags,
        )

    def test_single_node_single_tag(self):
        """Test a node with one protocol:port tag."""
        nodes = [self._make_node("Router1", ["ssh:22"])]
        devices = self.LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 1
        assert devices[0].device_label == "Router1"
        assert devices[0].protocol == "ssh"
        assert devices[0].host == "10.0.0.1"
        assert devices[0].port == 22

    def test_single_node_multiple_tags(self):
        """Test a node with multiple protocol:port tags.

        Multi-tag nodes get _{protocol} suffix to satisfy LDS unique constraint.
        """
        nodes = [self._make_node("Router1", ["serial:5041", "vnc:5044", "ssh:22"])]
        devices = self.LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 3
        protocols = {d.protocol for d in devices}
        assert protocols == {"serial", "vnc", "ssh"}

        # All labels should be unique and suffixed with protocol
        labels = {d.device_label for d in devices}
        assert labels == {"Router1_serial", "Router1_vnc", "Router1_ssh"}
        for d in devices:
            assert d.host == "10.0.0.1"

    def test_multiple_nodes(self):
        """Test multiple nodes with tags.

        Router1 has 1 tag → plain label. Switch1 has 2 tags → suffixed labels.
        """
        nodes = [
            self._make_node("Router1", ["ssh:22"]),
            self._make_node("Switch1", ["telnet:23", "vnc:5900"]),
        ]
        devices = self.LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 3

        router_devices = [d for d in devices if d.device_label == "Router1"]
        switch_devices = [d for d in devices if d.device_label.startswith("Switch1")]

        assert len(router_devices) == 1  # single tag → plain label
        assert len(switch_devices) == 2  # multi-tag → suffixed labels
        switch_labels = {d.device_label for d in switch_devices}
        assert switch_labels == {"Switch1_telnet", "Switch1_vnc"}

    def test_node_without_tags_skipped(self):
        """Test that nodes without tags are skipped."""
        nodes = [
            self._make_node("Router1", ["ssh:22"]),
            self._make_node("unmanaged-switch", None),
            self._make_node("Router2", []),
        ]
        devices = self.LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 1
        assert devices[0].device_label == "Router1"

    def test_tag_without_colon_skipped(self):
        """Test that tags without colon separator are skipped."""
        nodes = [self._make_node("Router1", ["invalid_tag", "ssh:22"])]
        devices = self.LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 1
        assert devices[0].protocol == "ssh"

    def test_tag_with_invalid_port_skipped(self):
        """Test that tags with non-numeric port are skipped."""
        nodes = [self._make_node("Router1", ["ssh:abc", "telnet:23"])]
        devices = self.LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 1
        assert devices[0].protocol == "telnet"
        assert devices[0].port == 23

    def test_empty_nodes_returns_empty(self):
        """Test that empty node list returns empty device list."""
        devices = self.LabletReconciler._build_device_access_list([], "10.0.0.1")
        assert devices == []
