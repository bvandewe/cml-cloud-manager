"""WorkerTemplate commands package."""

from application.commands.worker_template.create_worker_template_command import (
    CreateWorkerTemplateCommand,
    CreateWorkerTemplateCommandHandler,
)
from application.commands.worker_template.delete_worker_template_command import (
    DeleteWorkerTemplateCommand,
    DeleteWorkerTemplateCommandHandler,
)
from application.commands.worker_template.disable_worker_template_command import (
    DisableWorkerTemplateCommand,
    DisableWorkerTemplateCommandHandler,
)
from application.commands.worker_template.enable_worker_template_command import (
    EnableWorkerTemplateCommand,
    EnableWorkerTemplateCommandHandler,
)
from application.commands.worker_template.update_worker_template_command import (
    UpdateWorkerTemplateCommand,
    UpdateWorkerTemplateCommandHandler,
)

__all__ = [
    "CreateWorkerTemplateCommand",
    "CreateWorkerTemplateCommandHandler",
    "DeleteWorkerTemplateCommand",
    "DeleteWorkerTemplateCommandHandler",
    "DisableWorkerTemplateCommand",
    "DisableWorkerTemplateCommandHandler",
    "EnableWorkerTemplateCommand",
    "EnableWorkerTemplateCommandHandler",
    "UpdateWorkerTemplateCommand",
    "UpdateWorkerTemplateCommandHandler",
]
