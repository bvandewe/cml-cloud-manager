"""LabRecord CRUD helpers via Control Plane API.

ADR-038 Task 3: Extracted from LabletReconciler._find_lab_record_id(),
_register_lab_record(), and _update_lab_record_status().
"""

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.enums.lab_record_status import LabRecordStatus
from lcm_core.integration.clients import ControlPlaneApiClient

from integration.services.cml_labs_spi import CmlLabsSpiClient

logger = logging.getLogger(__name__)


async def find_lab_record_id(
    cml_lab_id: str,
    worker_id: str,
    api: ControlPlaneApiClient,
) -> str | None:
    """Find the LabRecord aggregate ID for a CML lab on a specific worker.

    Queries CPA for lab records matching the worker and CML lab ID.

    Args:
        cml_lab_id: CML native lab ID.
        worker_id: Worker aggregate ID.
        api: Control Plane API client.

    Returns:
        LabRecord aggregate ID, or None if not found.
    """
    try:
        lab_records = await api.get_lab_records_for_worker(worker_id=worker_id)
        for lr in lab_records:
            if lr.get("lab_id") == cml_lab_id:
                return lr.get("id")
    except Exception as e:
        logger.warning(f"Failed to find LabRecord for lab {cml_lab_id} on worker {worker_id}: {e}")

    return None


async def register_lab_record(
    cml_lab_id: str,
    instance: LabletSessionReadModel,
    api: ControlPlaneApiClient,
    cml_labs: CmlLabsSpiClient,
) -> str | None:
    """Register a CML lab as a LabRecord in CPA via discover_lab_records().

    Called when a freshly imported lab (or pre-existing lab without a LabRecord)
    needs to be registered immediately, rather than waiting for the background
    LabDiscoveryService scan.

    Args:
        cml_lab_id: CML native lab ID (from import or reuse).
        instance: LabletSession with worker credentials and IDs.
        api: Control Plane API client.
        cml_labs: CML Labs SPI client.

    Returns:
        LabRecord aggregate ID, or None if registration failed.
    """
    try:
        # 1. Fetch lab details from CML
        lab_info = await cml_labs.get_lab(
            host=instance.worker_ip,
            lab_id=cml_lab_id,
            username=instance.worker_cml_username,
            password=instance.worker_cml_password,
        )
        if not lab_info:
            logger.error(f"Cannot register LabRecord: lab {cml_lab_id} not found on worker {instance.worker_ip}")
            return None

        # 2. Map CML state to LabRecordStatus
        cml_state = lab_info.state.value if hasattr(lab_info.state, "value") else str(lab_info.state)
        status_mapping = {
            "DEFINED_ON_CORE": LabRecordStatus.DEFINED.value,
            "STARTED": LabRecordStatus.BOOTED.value,
            "BOOTED": LabRecordStatus.BOOTED.value,
            "STOPPED": LabRecordStatus.STOPPED.value,
            "QUEUED": LabRecordStatus.QUEUED.value,
        }
        status = status_mapping.get(cml_state, LabRecordStatus.DISCOVERED.value)

        # 3. Build lab data entry (same schema as LabDiscoveryService)
        lab_entry: dict[str, Any] = {
            "id": lab_info.id,
            "title": lab_info.title,
            "description": lab_info.description,
            "notes": lab_info.notes,
            "state": cml_state,
            "status": status,
            "owner": lab_info.owner,
            "owner_username": lab_info.owner_username,
            "node_count": lab_info.node_count,
            "link_count": lab_info.link_count,
            "created_at": lab_info.created_at.isoformat() if lab_info.created_at else None,
            "modified_at": lab_info.modified_at.isoformat() if lab_info.modified_at else None,
            "worker_ip": instance.worker_ip,
            "based_on_definition_id": instance.definition_id or None,
        }

        # 4. Register via CPA discover_lab_records()
        #    partial_scan=True: single-lab registration must NOT orphan other labs
        result = await api.discover_lab_records(
            worker_id=instance.worker_id,
            labs=[lab_entry],
            source="pipeline-lab-resolve",
            partial_scan=True,
        )
        discovered = result.get("discovered", 0)
        updated = result.get("updated", 0)
        logger.info(f"📋 Registered lab {cml_lab_id} via discover_lab_records: discovered={discovered}, updated={updated}")

        # 5. Look up the newly created LabRecord ID
        lab_record_id = await find_lab_record_id(cml_lab_id, instance.worker_id, api)
        if lab_record_id:
            logger.info(f"✅ LabRecord {lab_record_id} created for lab {cml_lab_id}")
        else:
            logger.error(f"LabRecord not found after discover_lab_records for lab {cml_lab_id}")
        return lab_record_id

    except Exception as e:
        logger.error(f"Failed to register LabRecord for lab {cml_lab_id} on worker {instance.worker_id}: {e}")
        return None


async def update_lab_record_status(
    cml_lab_id: str,
    worker_id: str,
    new_status: str,
    api: ControlPlaneApiClient,
) -> None:
    """Update a lab record's status via CPA.

    Graceful: logs failures but does not propagate exceptions.

    Args:
        cml_lab_id: CML native lab ID.
        worker_id: Worker aggregate ID.
        new_status: New LabRecordStatus value (lowercase).
        api: Control Plane API client.
    """
    try:
        lab_record_id = await find_lab_record_id(cml_lab_id, worker_id, api)
        if lab_record_id:
            await api.update_lab_record_status(
                lab_record_id=lab_record_id,
                new_status=new_status,
            )
    except Exception as e:
        logger.warning(f"Failed to update lab record status for lab {cml_lab_id}: {e}")
