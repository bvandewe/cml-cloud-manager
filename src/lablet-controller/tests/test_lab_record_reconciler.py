"""Focused unit tests for LabRecordReconciler delete orchestration."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from application.hosted_services.lab_record_reconciler import LabRecordReconciler
from integration.services.cml_labs_spi import LabInfo, LabState


def make_reconciler() -> LabRecordReconciler:
    """Create a LabRecordReconciler bypassing __init__ for focused tests."""
    reconciler = object.__new__(LabRecordReconciler)
    reconciler._api = MagicMock()
    reconciler._api.get_worker = AsyncMock()
    reconciler._api.update_lab_record_status = AsyncMock()
    reconciler._api.complete_lab_action = AsyncMock()
    reconciler._api.fail_lab_action = AsyncMock()
    reconciler._cml_labs = MagicMock()
    reconciler._cml_labs.get_lab = AsyncMock()
    reconciler._cml_labs.get_lab_state = AsyncMock()
    reconciler._cml_labs.stop_lab = AsyncMock()
    reconciler._cml_labs.wipe_lab = AsyncMock()
    reconciler._cml_labs.delete_lab = AsyncMock()
    reconciler._cml_labs.start_lab = AsyncMock()
    reconciler._settings = MagicMock()
    reconciler._settings.lab_action_timeout_seconds = 5
    reconciler._settings.lab_action_poll_interval_seconds = 0
    reconciler._settings.use_private_ip_for_monitoring = False
    reconciler._worker_host_cache = {}
    reconciler._actions_received = 0
    reconciler._actions_succeeded = 0
    reconciler._actions_failed = 0
    reconciler._actions_skipped = 0
    reconciler._last_action_at = None
    reconciler._last_error = None
    return reconciler


def make_lab(state: LabState) -> LabInfo:
    """Create a minimal LabInfo for orchestration tests."""
    return LabInfo(id="lab-001", title="Test Lab", state=state)


class TestLabRecordReconcilerDeleteFlow:
    """Delete orchestration tests."""

    @pytest.mark.asyncio
    async def test_delete_orchestrates_stop_wipe_delete_for_running_lab(self) -> None:
        reconciler = make_reconciler()
        reconciler._api.get_worker.return_value = {"public_ip": "1.1.1.1"}
        get_lab = AsyncMock(side_effect=[make_lab(LabState.STARTED), None])
        get_lab_state = AsyncMock(return_value=LabState.STOPPED)
        stop_lab = AsyncMock()
        wipe_lab = AsyncMock()
        delete_lab = AsyncMock()
        setattr(reconciler._cml_labs, "get_lab", get_lab)
        setattr(reconciler._cml_labs, "get_lab_state", get_lab_state)
        setattr(reconciler._cml_labs, "stop_lab", stop_lab)
        setattr(reconciler._cml_labs, "wipe_lab", wipe_lab)
        setattr(reconciler._cml_labs, "delete_lab", delete_lab)

        await reconciler._execute_action(
            lab_record_id="lr-001",
            action="delete",
            lab_id="lab-001",
            worker_id="worker-001",
        )

        stop_lab.assert_awaited_once_with(host="1.1.1.1", lab_id="lab-001")
        wipe_lab.assert_awaited_once_with(host="1.1.1.1", lab_id="lab-001")
        delete_lab.assert_awaited_once_with(host="1.1.1.1", lab_id="lab-001")
        assert reconciler._api.update_lab_record_status.await_args_list == [
            call(lab_record_id="lr-001", new_status="stopped", cml_state="STOPPED"),
            call(lab_record_id="lr-001", new_status="wiped", cml_state="DEFINED_ON_CORE"),
        ]
        reconciler._api.complete_lab_action.assert_awaited_once_with(
            lab_record_id="lr-001",
            action="delete",
        )
        reconciler._api.fail_lab_action.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_skips_stop_for_already_defined_lab(self) -> None:
        reconciler = make_reconciler()
        reconciler._api.get_worker.return_value = {"public_ip": "1.1.1.1"}
        get_lab = AsyncMock(side_effect=[make_lab(LabState.DEFINED_ON_CORE), None])
        get_lab_state = AsyncMock()
        stop_lab = AsyncMock()
        wipe_lab = AsyncMock()
        delete_lab = AsyncMock()
        setattr(reconciler._cml_labs, "get_lab", get_lab)
        setattr(reconciler._cml_labs, "get_lab_state", get_lab_state)
        setattr(reconciler._cml_labs, "stop_lab", stop_lab)
        setattr(reconciler._cml_labs, "wipe_lab", wipe_lab)
        setattr(reconciler._cml_labs, "delete_lab", delete_lab)

        await reconciler._execute_action(
            lab_record_id="lr-001",
            action="delete",
            lab_id="lab-001",
            worker_id="worker-001",
        )

        stop_lab.assert_not_awaited()
        get_lab_state.assert_not_awaited()
        wipe_lab.assert_awaited_once_with(host="1.1.1.1", lab_id="lab-001")
        delete_lab.assert_awaited_once_with(host="1.1.1.1", lab_id="lab-001")
        assert reconciler._api.update_lab_record_status.await_args_list == [
            call(lab_record_id="lr-001", new_status="wiped", cml_state="DEFINED_ON_CORE"),
        ]
        reconciler._api.complete_lab_action.assert_awaited_once_with(
            lab_record_id="lr-001",
            action="delete",
        )

    @pytest.mark.asyncio
    async def test_retries_action_after_refreshing_worker_host(self) -> None:
        reconciler = make_reconciler()
        reconciler._api.get_worker.side_effect = [
            {"public_ip": "1.1.1.1"},
            {"public_ip": "2.2.2.2"},
        ]
        wipe_lab = AsyncMock(side_effect=[RuntimeError("stale host"), None])
        setattr(reconciler._cml_labs, "wipe_lab", wipe_lab)

        await reconciler._execute_action(
            lab_record_id="lr-001",
            action="wipe",
            lab_id="lab-001",
            worker_id="worker-001",
        )

        assert wipe_lab.await_args_list == [
            call(host="1.1.1.1", lab_id="lab-001"),
            call(host="2.2.2.2", lab_id="lab-001"),
        ]
        reconciler._api.complete_lab_action.assert_awaited_once_with(
            lab_record_id="lr-001",
            action="wipe",
        )
        reconciler._api.fail_lab_action.assert_not_awaited()
