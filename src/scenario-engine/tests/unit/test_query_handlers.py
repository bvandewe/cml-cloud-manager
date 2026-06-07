"""Unit tests for CQRS query handlers."""

from unittest.mock import AsyncMock, patch

import pytest
from application.dtos.job_dto import JobDto
from application.queries.get_job_query import GetJobQuery, GetJobQueryHandler
from application.queries.list_scenarios_query import ListScenariosQuery, ListScenariosQueryHandler
from domain.entities.job import Job

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_job_repository():
    repo = AsyncMock()
    repo.get_by_id_async = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def fake_registry():
    """A registry dict with multiple scenarios."""
    return {
        "hello-world@v1": {
            "name": "hello-world",
            "version": "v1",
            "description": "Hello World scenario",
            "input_schema": {},
            "output_schema": {},
        },
        "lab-resolve@v1": {
            "name": "lab-resolve",
            "version": "v1",
            "description": "Resolve lab topology",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        },
        "lab-resolve@v2": {
            "name": "lab-resolve",
            "version": "v2",
            "description": "Resolve lab topology v2",
            "input_schema": {},
            "output_schema": {},
        },
    }


# =============================================================================
# GetJobQueryHandler
# =============================================================================


class TestGetJobQueryHandler:
    """Tests for GetJobQueryHandler."""

    @pytest.mark.unit
    async def test_get_job_happy_path(self, mock_job_repository):
        job = Job.create(
            scenario_name="hello-world",
            scenario_version="v1",
            input_data={"key": "value"},
            callback_url="http://localhost/events",
        )
        mock_job_repository.get_by_id_async = AsyncMock(return_value=job)

        handler = GetJobQueryHandler(job_repository=mock_job_repository)
        query = GetJobQuery(job_id=job.id())

        result = await handler.handle_async(query)

        assert result.is_success
        assert result.status_code == 200
        dto = result.data
        assert isinstance(dto, JobDto)
        assert dto.id == job.id()
        assert dto.scenario_name == "hello-world"
        assert dto.scenario_version == "v1"
        assert dto.status == "submitted"

    @pytest.mark.unit
    async def test_get_job_missing_job_id(self, mock_job_repository):
        handler = GetJobQueryHandler(job_repository=mock_job_repository)
        query = GetJobQuery(job_id="")

        result = await handler.handle_async(query)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.unit
    async def test_get_job_not_found(self, mock_job_repository):
        mock_job_repository.get_by_id_async = AsyncMock(return_value=None)

        handler = GetJobQueryHandler(job_repository=mock_job_repository)
        query = GetJobQuery(job_id="job-nonexistent")

        result = await handler.handle_async(query)

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# ListScenariosQueryHandler
# =============================================================================


class TestListScenariosQueryHandler:
    """Tests for ListScenariosQueryHandler."""

    @pytest.mark.unit
    async def test_list_all_scenarios(self, fake_registry):
        handler = ListScenariosQueryHandler()

        with patch("application.queries.list_scenarios_query.get_all_scenarios", return_value=fake_registry):
            query = ListScenariosQuery()
            result = await handler.handle_async(query)

        assert result.is_success
        assert result.status_code == 200
        data = result.data
        assert len(data) == 3
        names = {s["name"] for s in data}
        assert "hello-world" in names
        assert "lab-resolve" in names

    @pytest.mark.unit
    async def test_list_scenarios_with_name_filter(self, fake_registry):
        handler = ListScenariosQueryHandler()

        with patch("application.queries.list_scenarios_query.get_all_scenarios", return_value=fake_registry):
            query = ListScenariosQuery(name_filter="lab-")
            result = await handler.handle_async(query)

        assert result.is_success
        assert result.status_code == 200
        data = result.data
        assert len(data) == 2
        assert all(s["name"].startswith("lab-") for s in data)

    @pytest.mark.unit
    async def test_list_scenarios_filter_no_match(self, fake_registry):
        handler = ListScenariosQueryHandler()

        with patch("application.queries.list_scenarios_query.get_all_scenarios", return_value=fake_registry):
            query = ListScenariosQuery(name_filter="nonexistent")
            result = await handler.handle_async(query)

        assert result.is_success
        assert result.status_code == 200
        assert result.data == []

    @pytest.mark.unit
    async def test_list_scenarios_empty_registry(self):
        handler = ListScenariosQueryHandler()

        with patch("application.queries.list_scenarios_query.get_all_scenarios", return_value={}):
            query = ListScenariosQuery()
            result = await handler.handle_async(query)

        assert result.is_success
        assert result.status_code == 200
        assert result.data == []
