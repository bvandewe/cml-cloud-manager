"""Tests for GetCMLWorkersQuery."""

from unittest.mock import MagicMock

import pytest

from application.queries.get_cml_workers_query import GetCMLWorkersQuery, GetCMLWorkersQueryHandler
from domain.enums import CMLWorkerStatus
from integration.enums import AwsRegion
from tests.fixtures.mixins import BaseTestCase


class TestGetCMLWorkersQuery(BaseTestCase):
    """Test GetCMLWorkersQuery handler."""

    @pytest.fixture
    def handler(self, mock_repository: MagicMock) -> GetCMLWorkersQueryHandler:
        """Create a GetCMLWorkersQueryHandler with mocked repository."""
        return GetCMLWorkersQueryHandler(worker_repository=mock_repository)

    @pytest.mark.asyncio
    async def test_get_active_workers_default(self, handler: GetCMLWorkersQueryHandler, mock_repository: MagicMock) -> None:
        """Test that default query returns active workers."""
        # Arrange
        mock_repository.get_active_workers_async = self.create_async_mock(return_value=[])
        query = GetCMLWorkersQuery(aws_region=AwsRegion.US_EAST_1)

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        mock_repository.get_active_workers_async.assert_called_once()
        mock_repository.get_by_status_async.assert_not_called()
        mock_repository.get_all_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_status(self, handler: GetCMLWorkersQueryHandler, mock_repository: MagicMock) -> None:
        """Test querying by specific status."""
        # Arrange
        mock_repository.get_by_status_async = self.create_async_mock(return_value=[])
        query = GetCMLWorkersQuery(aws_region=AwsRegion.US_EAST_1, status=CMLWorkerStatus.RUNNING)

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        mock_repository.get_by_status_async.assert_called_once_with(CMLWorkerStatus.RUNNING)
        mock_repository.get_active_workers_async.assert_not_called()
        mock_repository.get_all_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_terminated(self, handler: GetCMLWorkersQueryHandler, mock_repository: MagicMock) -> None:
        """Test querying with include_terminated=True."""
        # Arrange
        mock_repository.get_all_async = self.create_async_mock(return_value=[])
        query = GetCMLWorkersQuery(aws_region=AwsRegion.US_EAST_1, include_terminated=True)

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        mock_repository.get_all_async.assert_called_once()
        mock_repository.get_active_workers_async.assert_not_called()
        mock_repository.get_by_status_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_takes_precedence_over_include_terminated(self, handler: GetCMLWorkersQueryHandler, mock_repository: MagicMock) -> None:
        """Test that status filter takes precedence over include_terminated."""
        # Arrange
        mock_repository.get_by_status_async = self.create_async_mock(return_value=[])
        query = GetCMLWorkersQuery(aws_region=AwsRegion.US_EAST_1, status=CMLWorkerStatus.RUNNING, include_terminated=True)

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        mock_repository.get_by_status_async.assert_called_once_with(CMLWorkerStatus.RUNNING)
        mock_repository.get_all_async.assert_not_called()
        mock_repository.get_all_async.assert_not_called()
