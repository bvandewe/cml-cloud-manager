"""FastAPI dependencies for Scenario Engine.

Provides authentication and service dependencies for API endpoints.
"""

import logging

from fastapi import Request

logger = logging.getLogger(__name__)


def get_service_provider(request: Request):
    """Get the service provider from request state.

    Args:
        request: FastAPI request object with state

    Returns:
        Service provider instance from Neuroglia DI container.
    """
    return request.state.services
