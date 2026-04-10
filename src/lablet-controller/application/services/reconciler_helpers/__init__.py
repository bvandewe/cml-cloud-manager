"""Reconciler helpers package — extracted helper method clusters.

ADR-038 Task 3: These modules contain the helper logic previously inlined
in LabletReconciler.  Each module exports standalone async functions
(or sync helpers) that take explicit service dependencies.

Modules:
    - definition_cache: _get_definition with cache
    - worker_helpers: Worker details resolution and caching
    - lab_record_helpers: LabRecord CRUD via CPA
    - lab_resolution: Lab resolve / reuse / import
    - lds_helpers: LDS session provisioning, archival, device access
    - observation_helpers: Resource observation and reporting
    - run_history: Lab run completion recording
"""
