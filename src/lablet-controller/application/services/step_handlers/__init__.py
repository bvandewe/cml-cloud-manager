"""Step handlers package — all pipeline step implementations.

ADR-038: Importing this package triggers registration of all step handlers
via the ``@step_handler`` decorator side-effects. The reconciler imports
this package once at startup.

Handler modules:
    - instantiation_steps: content_sync, variables, lab_resolve
    - port_steps: ports_alloc, tags_sync
    - binding_steps: lab_binding, lds_provision, mark_ready
    - lab_lifecycle_steps: lab_start, stop_lab, wipe_lab
    - lds_steps: deregister_lds
    - archive_steps: archive
    - evidence_steps: capture_configs, capture_screenshots, export_pcaps, package_evidence
    - grading_steps: load_rubric, evaluate, record_score
"""

# Import all handler modules to trigger @step_handler registration.
# Order does not matter — registration is by name, not by import order.
from application.services.step_handlers import (
    archive_steps,  # noqa: F401
    binding_steps,  # noqa: F401
    cml_command_step,  # noqa: F401
    evidence_steps,  # noqa: F401
    grading_steps,  # noqa: F401
    instantiation_steps,  # noqa: F401
    lab_lifecycle_steps,  # noqa: F401
    lds_steps,  # noqa: F401
    port_steps,  # noqa: F401
)
