"""Step handlers package — all pipeline step implementations.

Importing this package triggers registration of all step handlers
via the ``@step_handler`` decorator side-effects. The reconciler imports
this package once at startup.

Each step handler lives in its own module (one step per file):
    - content_sync_step: content_sync
    - variables_step: variables
    - lab_resolve_step: lab_resolve
    - ports_alloc_step: ports_alloc
    - tags_sync_step: tags_sync
    - lab_binding_step: lab_binding
    - lab_start_step: lab_start
    - lds_provision_step: lds_provision
    - mark_ready_step: mark_ready
    - stop_lab_step: stop_lab
    - deregister_lds_step: deregister_lds
    - wipe_lab_step: wipe_lab
    - archive_step: archive
    - capture_configs_step: capture_configs
    - capture_screenshots_step: capture_screenshots
    - export_pcaps_step: export_pcaps
    - package_evidence_step: package_evidence
    - load_rubric_step: load_rubric
    - evaluate_step: evaluate
    - record_score_step: record_score
    - cml_command_step: execute_command_on_cml_node
"""

# Import all handler modules to trigger @step_handler registration.
# Order does not matter — registration is by name, not by import order.
from application.services.step_handlers import (
    archive_step,  # noqa: F401
    capture_configs_step,  # noqa: F401
    capture_screenshots_step,  # noqa: F401
    cml_command_step,  # noqa: F401
    content_sync_step,  # noqa: F401
    deregister_lds_step,  # noqa: F401
    evaluate_step,  # noqa: F401
    export_pcaps_step,  # noqa: F401
    lab_binding_step,  # noqa: F401
    lab_resolve_step,  # noqa: F401
    lab_start_step,  # noqa: F401
    lds_provision_step,  # noqa: F401
    load_rubric_step,  # noqa: F401
    mark_ready_step,  # noqa: F401
    package_evidence_step,  # noqa: F401
    ports_alloc_step,  # noqa: F401
    record_score_step,  # noqa: F401
    stop_lab_step,  # noqa: F401
    tags_sync_step,  # noqa: F401
    variables_step,  # noqa: F401
    wipe_lab_step,  # noqa: F401
)
