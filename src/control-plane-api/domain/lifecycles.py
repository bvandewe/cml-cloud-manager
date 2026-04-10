"""Lifecycle definitions for domain aggregates.

ADR-036 §2.1.4: Each aggregate type defines its lifecycle as a ManagedLifecycle
constant — an ordered set of LifecyclePhases that execute during the resource's
lifetime.

These constants are assigned to TimedResourceState.lifecycle when the aggregate
is created (via @dispatch event handlers).
"""

from lcm_core.domain.value_objects.managed_lifecycle import LifecyclePhase, ManagedLifecycle

# ---------------------------------------------------------------------------
# CML Worker Lifecycle
# ---------------------------------------------------------------------------
# Represents the full lifecycle of an AWS EC2 instance running Cisco Modeling
# Lab. Phases execute in order; optional phases (is_required=False) may be
# skipped based on runtime detection (e.g., Personal AMI ≤20 nodes needs no
# license registration).
#
# State machine context (CMLWorkerStatus):
#   pending → provisioning → starting → running → draining →
#   stopping → stopped → terminating → terminated
#
# Phase-to-status mapping:
#   provision        → triggered when PENDING
#   startup          → triggered during PROVISIONING (continues through STARTING)
#   initial_metrics  → triggered during STARTING (first metrics collection)
#   license_register → triggered during STARTING (optional: Enterprise AMI only)
#   monitor_resources → triggered when RUNNING (recurrent metrics pipeline)
#   drain            → triggered when DRAINING
#   teardown         → triggered during STOPPING/TERMINATING
#   terminate        → triggered when TERMINATING (final cleanup)
# ---------------------------------------------------------------------------

CML_WORKER_LIFECYCLE = ManagedLifecycle(
    phases=(
        LifecyclePhase(
            name="provision",
            engine="pipeline",
            trigger_on_status="pending",
            is_required=True,
        ),
        LifecyclePhase(
            name="startup",
            engine="pipeline",
            trigger_on_status="provisioning",
            is_required=True,
        ),
        LifecyclePhase(
            name="initial_metrics",
            engine="pipeline",
            trigger_on_status="starting",
            is_required=True,
        ),
        LifecyclePhase(
            name="license_register",
            engine="pipeline",
            trigger_on_status="starting",
            is_required=False,  # Only for Enterprise AMI (≤300 nodes); skipped for Personal AMI (≤20 nodes)
        ),
        LifecyclePhase(
            name="monitor_resources",
            engine="pipeline",
            trigger_on_status="running",
            is_required=True,
        ),
        LifecyclePhase(
            name="drain",
            engine="pipeline",
            trigger_on_status="draining",
            is_required=True,
        ),
        LifecyclePhase(
            name="teardown",
            engine="pipeline",
            trigger_on_status="stopping",
            is_required=True,
        ),
        LifecyclePhase(
            name="terminate",
            engine="pipeline",
            trigger_on_status="terminating",
            is_required=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
# LabletSession Lifecycle
# ---------------------------------------------------------------------------
# Represents the full lifecycle of a LabletSession — a time-bounded user
# experience combining a CML lab, LDS session, and optional grading.
#
# State machine context (LabletSessionStatus):
#   pending → scheduled → instantiating → ready → running → collecting →
#   grading → stopping → stopped → archived
#   + terminated (from any non-terminal state)
#   + expired (from instantiating/ready/running/collecting/grading)
#
# Phase-to-status mapping:
#   schedule          → triggered when PENDING (assign to worker)
#   instantiate       → triggered when SCHEDULED (import lab, start CML)
#   activate          → triggered when READY (wait for user login via LDS)
#   monitor           → triggered when RUNNING (active session monitoring)
#   collect_evidence  → triggered when COLLECTING (optional: assessment data)
#   compute_grading   → triggered when GRADING (optional: grade evaluation)
#   teardown          → triggered when STOPPING (session shutdown)
#   archive           → triggered when STOPPED (optional: post-shutdown)
#   expire            → triggered when EXPIRED (timeslot expiry cleanup)
#   terminate         → triggered when TERMINATED (emergency cleanup)
# ---------------------------------------------------------------------------

LABLET_SESSION_LIFECYCLE = ManagedLifecycle(
    phases=(
        LifecyclePhase(
            name="schedule",
            engine="pipeline",
            trigger_on_status="pending",
            is_required=True,
        ),
        LifecyclePhase(
            name="instantiate",
            engine="pipeline",
            trigger_on_status="scheduled",
            is_required=True,
        ),
        LifecyclePhase(
            name="activate",
            engine="pipeline",
            trigger_on_status="ready",
            is_required=True,
        ),
        LifecyclePhase(
            name="monitor",
            engine="pipeline",
            trigger_on_status="running",
            is_required=True,
        ),
        LifecyclePhase(
            name="collect_evidence",
            engine="pipeline",
            trigger_on_status="collecting",
            is_required=False,  # Not all sessions have assessment
        ),
        LifecyclePhase(
            name="compute_grading",
            engine="pipeline",
            trigger_on_status="grading",
            is_required=False,  # Not all sessions have grading
        ),
        LifecyclePhase(
            name="teardown",
            engine="pipeline",
            trigger_on_status="stopping",
            is_required=True,
        ),
        LifecyclePhase(
            name="archive",
            engine="pipeline",
            trigger_on_status="stopped",
            is_required=False,  # Archival is optional
        ),
        LifecyclePhase(
            name="expire",
            engine="pipeline",
            trigger_on_status="expired",
            is_required=True,
        ),
        LifecyclePhase(
            name="terminate",
            engine="pipeline",
            trigger_on_status="terminated",
            is_required=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
# LabletDefinition Lifecycle
# ---------------------------------------------------------------------------
# Represents the lifecycle of a LabletDefinition — a versioned template
# for creating lab instances. Definitions must sync content from upstream
# before becoming active, and can be deprecated or archived.
#
# State machine context (LabletDefinitionStatus):
#   pending_sync → active → deprecated → archived
#
# Phase-to-status mapping:
#   sync_content → triggered when PENDING_SYNC (download + upload content)
#   activate     → triggered when ACTIVE (definition ready for instantiation)
#   deprecate    → triggered when DEPRECATED (optional: notify dependents)
#   archive      → triggered when ARCHIVED (optional: cleanup, remove artifacts)
# ---------------------------------------------------------------------------

LABLET_DEFINITION_LIFECYCLE = ManagedLifecycle(
    phases=(
        LifecyclePhase(
            name="sync_content",
            engine="pipeline",
            trigger_on_status="pending_sync",
            is_required=True,
        ),
        LifecyclePhase(
            name="activate",
            engine="pipeline",
            trigger_on_status="active",
            is_required=True,
        ),
        LifecyclePhase(
            name="deprecate",
            engine="pipeline",
            trigger_on_status="deprecated",
            is_required=False,  # Not all definitions are deprecated (some archived directly)
        ),
        LifecyclePhase(
            name="archive",
            engine="pipeline",
            trigger_on_status="archived",
            is_required=False,  # Archival is optional
        ),
    ),
)
