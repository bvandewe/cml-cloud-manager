"""Structured logging configuration for Lablet Cloud Manager.

This module provides structured logging configuration using Python's
standard logging with JSON formatting support and correlation ID tracking.
"""

import contextvars
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

# Context variable for correlation ID (thread-safe and async-safe)
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

# Context variable for user context
user_context_var: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("user_context", default=None)


def get_correlation_id() -> str:
    """Get the current correlation ID, generating one if not set.

    Returns:
        The current correlation ID
    """
    cid = correlation_id_var.get()
    if cid is None:
        cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context.

    Args:
        correlation_id: The correlation ID to set
    """
    correlation_id_var.set(correlation_id)


def set_user_context(user_id: str = "", username: str = "", roles: list[str] = None):
    """Set user context for the current request.

    Args:
        user_id: The user's ID
        username: The user's username
        roles: The user's roles
    """
    context = {}
    if user_id:
        context["user_id"] = user_id
    if username:
        context["username"] = username
    if roles:
        context["roles"] = ",".join(roles)
    if context:
        user_context_var.set(context)


def clear_context() -> None:
    """Clear all context variables."""
    correlation_id_var.set(None)
    user_context_var.set(None)


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Produces JSON-formatted log entries with standard fields for
    cloud-native log aggregation systems.
    """

    def __init__(
        self,
        service_name: str = "lablet-cloud-manager",
        service_version: str = "1.0.0",
        environment: str = "development",
        include_traceback: bool = True,
    ):
        """Initialize the JSON formatter.

        Args:
            service_name: Name of the service
            service_version: Version of the service
            environment: Deployment environment (development, staging, production)
            include_traceback: Whether to include full tracebacks in error logs
        """
        super().__init__()
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment
        self.include_traceback = include_traceback

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON.

        Args:
            record: The log record to format

        Returns:
            JSON-formatted log string
        """
        # Build the base log entry
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": {
                "name": self.service_name,
                "version": self.service_version,
                "environment": self.environment,
            },
        }

        # Add correlation ID if available
        correlation_id = correlation_id_var.get()
        if correlation_id:
            log_entry["correlation_id"] = correlation_id

        # Add user context if available
        user_context = user_context_var.get()
        if user_context:
            log_entry["user"] = user_context

        # Add source location
        log_entry["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
            "module": record.module,
        }

        # Add OpenTelemetry trace context if available
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span.is_recording():
                span_context = span.get_span_context()
                log_entry["trace"] = {
                    "trace_id": format(span_context.trace_id, "032x"),
                    "span_id": format(span_context.span_id, "016x"),
                }
        except ImportError:
            pass
        except Exception:
            pass

        # Add exception info if present
        if record.exc_info:
            if self.include_traceback:
                log_entry["exception"] = {
                    "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                    "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                    "traceback": self.formatException(record.exc_info),
                }
            else:
                log_entry["exception"] = {
                    "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                    "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                }

        # Add any extra fields from the record
        # This allows structured fields to be passed via extra={"key": "value"}
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "taskName",
                "message",
            ):
                # Add custom fields under "context"
                if "context" not in log_entry:
                    log_entry["context"] = {}
                log_entry["context"][key] = value

        return json.dumps(log_entry, default=str)


class StructuredLogger:
    """Wrapper for structured logging with context awareness.

    Provides a convenient interface for logging with structured data
    and automatic context injection.
    """

    def __init__(self, name: str):
        """Initialize the structured logger.

        Args:
            name: Logger name (typically __name__)
        """
        self._logger = logging.getLogger(name)

    def _log(self, level: int, msg: str, **kwargs):
        """Log a message with structured data.

        Args:
            level: Log level
            msg: Log message
            **kwargs: Additional structured fields
        """
        self._logger.log(level, msg, extra=kwargs)

    def debug(self, msg: str, **kwargs):
        """Log a debug message with structured data."""
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        """Log an info message with structured data."""
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        """Log a warning message with structured data."""
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, exc_info: bool = False, **kwargs):
        """Log an error message with structured data."""
        self._logger.error(msg, exc_info=exc_info, extra=kwargs)

    def exception(self, msg: str, **kwargs):
        """Log an exception with structured data."""
        self._logger.exception(msg, extra=kwargs)

    # Domain-specific logging methods

    def log_instance_event(
        self,
        event: str,
        instance_id: str,
        definition_id: str = "",
        worker_id: str = "",
        state: str = "",
        **kwargs,
    ):
        """Log a lablet instance event.

        Args:
            event: Event name (e.g., "created", "scheduled", "terminated")
            instance_id: ID of the lablet instance
            definition_id: ID of the lablet definition
            worker_id: ID of the assigned worker
            state: Current state
            **kwargs: Additional context
        """
        self.info(
            f"Instance {event}",
            event_type=f"instance.{event}",
            instance_id=instance_id,
            definition_id=definition_id,
            worker_id=worker_id,
            state=state,
            **kwargs,
        )

    def log_worker_event(
        self,
        event: str,
        worker_id: str,
        template_id: str = "",
        state: str = "",
        **kwargs,
    ):
        """Log a worker event.

        Args:
            event: Event name (e.g., "created", "started", "stopped")
            worker_id: ID of the worker
            template_id: ID of the worker template
            state: Current state
            **kwargs: Additional context
        """
        self.info(
            f"Worker {event}",
            event_type=f"worker.{event}",
            worker_id=worker_id,
            template_id=template_id,
            state=state,
            **kwargs,
        )

    def log_scheduling_decision(
        self,
        action: str,
        instance_id: str = "",
        worker_id: str = "",
        reason: str = "",
        **kwargs,
    ):
        """Log a scheduling decision.

        Args:
            action: Scheduling action (e.g., "assign", "scale_up", "wait")
            instance_id: ID of the instance being scheduled
            worker_id: ID of the target worker
            reason: Reason for the decision
            **kwargs: Additional context
        """
        self.info(
            f"Scheduling decision: {action}",
            event_type="scheduling.decision",
            action=action,
            instance_id=instance_id,
            worker_id=worker_id,
            reason=reason,
            **kwargs,
        )

    def log_assessment_event(
        self,
        event: str,
        instance_id: str,
        phase: str = "",
        **kwargs,
    ):
        """Log an assessment event.

        Args:
            event: Event name (e.g., "started", "completed", "failed")
            instance_id: ID of the lablet instance
            phase: Assessment phase (collection, grading)
            **kwargs: Additional context
        """
        self.info(
            f"Assessment {event}",
            event_type=f"assessment.{event}",
            instance_id=instance_id,
            phase=phase,
            **kwargs,
        )

    def log_scaling_event(
        self,
        action: str,
        worker_id: str = "",
        template: str = "",
        reason: str = "",
        requested_by: str = "",
        aws_region: str = "",
        idle_minutes: float = 0,
        **kwargs,
    ):
        """Log a scaling lifecycle event for audit trail.

        Phase 3 - Auto-Scaling: Provides structured audit log of all
        scaling decisions across the system.

        Args:
            action: Scaling action (scale_up_accepted, scale_up_rejected,
                    drain_accepted, drain_rejected).
            worker_id: ID of the affected worker.
            template: Worker template name (for scale-up events).
            reason: Human-readable reason for the action.
            requested_by: System or user that requested the action.
            aws_region: AWS region for the scaling action.
            idle_minutes: How long the worker was idle (for drain events).
            **kwargs: Additional context.
        """
        self.info(
            f"Scaling: {action}",
            event_type=f"scaling.{action}",
            worker_id=worker_id,
            template=template,
            reason=reason,
            requested_by=requested_by,
            aws_region=aws_region,
            idle_minutes=idle_minutes,
            **kwargs,
        )


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name)


def configure_structured_logging(
    service_name: str = "lablet-cloud-manager",
    service_version: str = "1.0.0",
    environment: str = "development",
    log_level: str = "INFO",
    json_format: bool = True,
    console_output: bool = True,
    file_output: str = "",
):
    """Configure structured logging for the application.

    Args:
        service_name: Name of the service
        service_version: Version of the service
        environment: Deployment environment
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Whether to use JSON formatting
        console_output: Whether to output to console
        file_output: Path to log file (empty string to disable)
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Clear existing handlers
    root_logger.handlers.clear()

    # Set the log level
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Create formatter
    if json_format:
        formatter = JsonFormatter(
            service_name=service_name,
            service_version=service_version,
            environment=environment,
        )
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Add console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Add file handler if specified
    if file_output:
        try:
            from pathlib import Path

            Path(file_output).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(file_output)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            root_logger.warning(f"Failed to configure file logging: {e}")

    # Reduce noise from third-party loggers
    noisy_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "httpx",
        "httpcore",
        "pymongo",
        "asyncio",
        "opentelemetry",
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


__all__ = [
    "get_correlation_id",
    "set_correlation_id",
    "set_user_context",
    "clear_context",
    "correlation_id_var",
    "user_context_var",
    "JsonFormatter",
    "StructuredLogger",
    "get_logger",
    "configure_structured_logging",
]
