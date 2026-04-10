"""LDS session helpers — provisioning, archival, and device access.

ADR-038 Task 3: Extracted from LabletReconciler._build_device_access_list()
and _archive_lds_session().

Note: _provision_lds_session is NOT extracted here — it remains on the
reconciler because it orchestrates multiple services (CML, LDS, CPA)
with metric tracking and is only called from _handle_instantiating,
not from pipeline step handlers.
"""

import logging

from lcm_core.domain.entities import LabletSessionReadModel

from integration.services.cml_labs_spi import NodeInfo
from integration.services.lds_spi import DeviceAccessInfo, LdsSpiClient, LdsSpiError

logger = logging.getLogger(__name__)


def build_device_access_list(nodes: list[NodeInfo], worker_ip: str) -> list[DeviceAccessInfo]:
    """Build LDS device access info from CML node topology.

    AD-P4-03: CML node label = device_label, tags encode protocol:port.
    Tags format: ["serial:5041", "vnc:5044", "ssh:22"]

    Device labels must be unique per LDS session part (DB unique constraint
    on (ldssession_part_id, device_label)). When a node has multiple valid
    protocol tags, the label is suffixed with ``_{protocol}`` to ensure
    uniqueness (e.g., ``ubuntu-desktop_serial``, ``ubuntu-desktop_vnc``).
    Nodes with a single valid tag keep the plain label for backward compat.

    Args:
        nodes: CML lab nodes with labels and tags.
        worker_ip: Worker IP address for device host.

    Returns:
        List of DeviceAccessInfo for LDS device provisioning.
    """
    devices: list[DeviceAccessInfo] = []

    for node in nodes:
        if not node.tags:
            continue

        # First pass: collect valid (protocol, port) pairs for this node
        valid_pairs: list[tuple[str, int]] = []
        for tag in node.tags:
            if ":" not in tag:
                continue

            parts = tag.split(":", 1)
            if len(parts) != 2:
                continue

            protocol = parts[0].strip()
            try:
                port = int(parts[1].strip())
            except ValueError:
                logger.warning(f"Invalid port in tag '{tag}' for node '{node.label}'")
                continue

            valid_pairs.append((protocol, port))

        # Second pass: build devices with unique labels
        # Single tag → plain label; multiple tags → label_protocol
        use_suffix = len(valid_pairs) > 1
        for protocol, port in valid_pairs:
            device_label = f"{node.label}_{protocol}" if use_suffix else node.label
            devices.append(
                DeviceAccessInfo(
                    device_label=device_label,
                    protocol=protocol,
                    host=worker_ip,
                    port=port,
                )
            )

    return devices


async def archive_lds_session(
    instance: LabletSessionReadModel,
    lds: LdsSpiClient,
) -> bool:
    """Archive the LDS session for a session.

    Graceful: logs failures but does not propagate exceptions.

    Args:
        instance: Session with LDS session to archive.
        lds: LDS SPI client.

    Returns:
        True if the session was archived successfully, False otherwise.
    """
    if not instance.lds_session_id:
        return False

    try:
        await lds.archive_session(
            session_id=instance.lds_session_id,
            region=instance.worker_aws_region,
        )
        logger.info(f"Archived LDS session {instance.lds_session_id} for instance {instance.id}")
        return True
    except LdsSpiError as e:
        logger.warning(f"Failed to archive LDS session {instance.lds_session_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error archiving LDS session {instance.lds_session_id}: {e}")
        return False
