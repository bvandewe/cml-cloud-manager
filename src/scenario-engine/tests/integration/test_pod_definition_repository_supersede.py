"""Unit-style tests for MongoPodDefinitionRepository.expire_superseded_definitions_async().

The repository's mongo-facing surface (``self.collection``, ``self._deserialize_entity``,
``self.update_async``) is mocked so we can assert behaviour without spinning
up a real MongoDB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from domain.entities.pod_definition import PodDefinition
from integration.persistence.mongo_pod_definition_repository import MongoPodDefinitionRepository
from lcm_core.domain.enums.pod_definition_status import PodDefinitionStatus
from lcm_core.domain.enums.pod_type import PodType


class _AsyncIter:
    """Minimal async iterator wrapping a sync iterable."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self) -> Any:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _make_pod_definition(
    *,
    name: str,
    version: str,
    content_hash: str,
    pod_type: PodType = PodType.CML_ON_AWS,
    status: PodDefinitionStatus = PodDefinitionStatus.READY,
) -> PodDefinition:
    pd = PodDefinition.create(
        name=name,
        version=version,
        pod_type=pod_type,
        source_uri=f"s3://bucket/{name}-{version}.zip",
    )
    # Force the aggregate directly into the desired test arrangement without
    # spinning through every legal transition.
    pd.state.status = status
    pd.state.content_hash = content_hash
    return pd


@pytest.fixture
def repo() -> MongoPodDefinitionRepository:
    """Construct a repository instance without running ``__init__`` and mock
    the Mongo-facing collaborators we need."""
    instance = MongoPodDefinitionRepository.__new__(MongoPodDefinitionRepository)
    # ``collection`` is a cached property backed by ``_collection`` on the
    # MotorRepository base — assign to the backing field so the property
    # returns our mock.
    instance._collection = MagicMock()  # type: ignore[attr-defined]
    instance.update_async = AsyncMock()  # type: ignore[method-assign]
    instance._deserialize_entity = MagicMock()  # type: ignore[method-assign]
    return instance


@pytest.mark.asyncio
async def test_no_stale_definitions_returns_empty_list(repo: MongoPodDefinitionRepository) -> None:
    repo.collection.find.return_value = _AsyncIter([])

    result = await repo.expire_superseded_definitions_async(
        name="lab",
        pod_type=PodType.CML_ON_AWS,
        current_definition_id="pd-new",
        current_content_hash="hash-new",
    )

    assert result == []
    repo.update_async.assert_not_awaited()  # type: ignore[attr-defined]
    repo.collection.find.assert_called_once()
    query = repo.collection.find.call_args.args[0]
    assert query["name"] == "lab"
    assert query["pod_type"] == PodType.CML_ON_AWS.value
    assert query["status"] == PodDefinitionStatus.READY.value
    assert query["content_hash"] == {"$ne": "hash-new"}
    assert query["_id"] == {"$ne": "pd-new"}


@pytest.mark.asyncio
async def test_supersedes_stale_definitions(repo: MongoPodDefinitionRepository) -> None:
    stale_a = _make_pod_definition(name="lab", version="0.9", content_hash="hash-old-a")
    stale_b = _make_pod_definition(name="lab", version="0.8", content_hash="hash-old-b")
    docs = [{"_id": stale_a.state.id}, {"_id": stale_b.state.id}]
    repo.collection.find.return_value = _AsyncIter(docs)
    repo._deserialize_entity.side_effect = [stale_a, stale_b]  # type: ignore[attr-defined]

    result = await repo.expire_superseded_definitions_async(
        name="lab",
        pod_type=PodType.CML_ON_AWS,
        current_definition_id="pd-new",
        current_content_hash="hash-new",
    )

    assert set(result) == {stale_a.state.id, stale_b.state.id}
    assert stale_a.state.status == PodDefinitionStatus.SUPERSEDED
    assert stale_b.state.status == PodDefinitionStatus.SUPERSEDED
    # The aggregates must have recorded a PodDefinitionSupersededDomainEvent
    # carrying the new definition id.
    for stale in (stale_a, stale_b):
        superseded_events = [e for e in stale._pending_events if type(e).__name__ == "PodDefinitionSupersededDomainEvent"]
        assert len(superseded_events) == 1
        assert superseded_events[0].superseded_by == "pd-new"
    assert repo.update_async.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_skips_documents_that_fail_to_deserialize(repo: MongoPodDefinitionRepository) -> None:
    stale = _make_pod_definition(name="lab", version="0.9", content_hash="hash-old")
    repo.collection.find.return_value = _AsyncIter([{"_id": "bad"}, {"_id": stale.state.id}])
    repo._deserialize_entity.side_effect = [None, stale]  # type: ignore[attr-defined]

    result = await repo.expire_superseded_definitions_async(
        name="lab",
        pod_type=PodType.CML_ON_AWS,
        current_definition_id="pd-new",
        current_content_hash="hash-new",
    )

    assert result == [stale.state.id]
    repo.update_async.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_idempotent_when_called_twice(repo: MongoPodDefinitionRepository) -> None:
    # Second call sees an empty cursor — mirrors what happens after the first
    # call already transitioned the stale definitions to SUPERSEDED.
    repo.collection.find.return_value = _AsyncIter([])

    first = await repo.expire_superseded_definitions_async(
        name="lab",
        pod_type=PodType.CML_ON_AWS,
        current_definition_id="pd-new",
        current_content_hash="hash-new",
    )
    second = await repo.expire_superseded_definitions_async(
        name="lab",
        pod_type=PodType.CML_ON_AWS,
        current_definition_id="pd-new",
        current_content_hash="hash-new",
    )

    assert first == []
    assert second == []
    repo.update_async.assert_not_awaited()  # type: ignore[attr-defined]
