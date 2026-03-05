"""Centralized logging configuration for Lablet Cloud Manager services.

This module provides a unified logging configuration that can be imported by all
microservices (control-plane-api, resource-scheduler, lablet-controller, worker-controller).

Features:
- Consistent log format with filename and line number
- Optional file logging with truncation on startup
- Noise reduction for third-party libraries
- Cloud-native compatible (Docker, Kubernetes)

Usage:
    from lcm_core.infrastructure.logging import configure_logging

    # Basic usage
    configure_logging(log_level="DEBUG")

    # With file logging
    configure_logging(
        log_level="DEBUG",
        log_to_file=True,
        log_file="logs/my-service.log",
        truncate_on_start=True
    )
"""

import logging
import os
import sys
from pathlib import Path


def configure_logging(
    log_level: str = "INFO",
    log_to_file: bool | None = None,
    log_file: str | None = None,
    truncate_on_start: bool | None = None,
) -> None:
    """Configure application-wide logging with support for console and file output.

    This function configures the root logger and sets appropriate levels for
    third-party libraries to reduce noise. It's designed to be portable and
    work across different deployment environments (local, Docker, Kubernetes).

    Environment variables (override parameters if set):
        LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        LOG_TO_FILE: Enable file logging ("true", "1", "yes")
        LOG_FILE: Path to log file (default: logs/debug.log)
        LOG_FILE_TRUNCATE_ON_START: Truncate log file on startup ("true", "1", "yes")

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Enable file logging. If None, uses LOG_TO_FILE env var or defaults to False
        log_file: Path to log file. If None, uses LOG_FILE env var or defaults to logs/debug.log
        truncate_on_start: Truncate log file on startup. If None, uses LOG_FILE_TRUNCATE_ON_START
                          env var or defaults to True when file logging is enabled
    """
    # Resolve settings from environment variables with fallbacks to parameters
    log_level = os.getenv("LOG_LEVEL", log_level).upper()

    # Resolve log_to_file
    env_log_to_file = os.getenv("LOG_TO_FILE", "").lower()
    if env_log_to_file:
        log_to_file = env_log_to_file in ("true", "1", "yes")
    elif log_to_file is None:
        log_to_file = False

    # Resolve log_file path
    log_file = os.getenv("LOG_FILE", log_file or "logs/debug.log")

    # Resolve truncate_on_start
    env_truncate = os.getenv("LOG_FILE_TRUNCATE_ON_START", "").lower()
    if env_truncate:
        truncate_on_start = env_truncate in ("true", "1", "yes")
    elif truncate_on_start is None:
        # Default to True when file logging is enabled
        truncate_on_start = log_to_file

    # Get root logger and clear any existing handlers to prevent duplicates
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Set the root logger level
    root_logger.setLevel(log_level)

    # Define log format with filename and line number (no logger name to avoid duplication)
    log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    formatter = logging.Formatter(log_format)

    # Console handler (always enabled for cloud-native environments)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_to_file:
        try:
            # Resolve log file path
            log_path = Path(log_file)
            if not log_path.is_absolute():
                # Make relative paths relative to current working directory
                log_path = Path.cwd() / log_path

            # Create directory if needed
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Truncate file if requested (creates empty file)
            if truncate_on_start and log_path.exists():
                log_path.write_text("")

            # Create file handler
            file_handler = logging.FileHandler(str(log_path))
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

            # Log successful file handler setup
            root_logger.debug(f"File logging enabled: {log_path}")
        except (OSError, PermissionError) as e:
            # Log warning but don't fail - console logging still works
            root_logger.warning(f"Could not enable file logging to {log_file}: {e}")

    # Set third-party loggers to WARNING to reduce noise
    noisy_loggers_warning = [
        # Infrastructure/HTTP libraries
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "starlette",
        "httpx",
        "httpcore",
        "httpcore.http11",
        "httpcore.connection",
        "h11",
        "h11._readers",
        "h11._writers",
        "aiohttp",
        "aiohttp.access",
        "asyncio",
        "concurrent.futures",
        # AWS libraries
        "botocore",
        "botocore.credentials",
        "botocore.endpoint",
        "botocore.httpsession",
        "botocore.hooks",
        "botocore.loaders",
        "botocore.parsers",
        "botocore.retryhandler",
        "botocore.utils",
        "boto3",
        "boto3.resources",
        "urllib3",
        "urllib3.connectionpool",
        "urllib3.util.retry",
        "s3transfer",
        # MongoDB
        "pymongo",
        "pymongo.topology",
        "pymongo.connection",
        "pymongo.serverSelection",
        "pymongo.command",
        "motor",
        # etcd
        "etcd3",
        "grpc",
        "grpc._channel",
        "grpc._server",
        # OpenTelemetry
        "opentelemetry",
        "opentelemetry.sdk",
        "opentelemetry.exporter",
        "opentelemetry.instrumentation",
        # Other
        "watchfiles",
        "multipart",
        "charset_normalizer",
        "pydantic",
    ]

    for logger_name in noisy_loggers_warning:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Set repetitive framework loggers to INFO (skip DEBUG-level spam)
    repetitive_loggers_info = [
        # Neuroglia middleware - very chatty at DEBUG
        "neuroglia.mediation.metrics_middleware",
        "neuroglia.mediation.tracing_middleware",
        "neuroglia.mediation.logging_middleware",
        "neuroglia.mediation.validation_middleware",
        "neuroglia.hosting",
        # LCM-core leader election - lease renewals every 5s
        "lcm_core.infrastructure.hosted_services.leader_elected_hosted_service",
        "lcm_core.infrastructure.hosted_services.reconciliation_hosted_service",
        # etcd client internals
        "lcm_core.integration.clients.etcd_client",
    ]

    for logger_name in repetitive_loggers_info:
        logging.getLogger(logger_name).setLevel(logging.INFO)
