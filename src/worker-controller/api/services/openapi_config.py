"""OpenAPI configuration for Swagger UI authentication."""

import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

logger = logging.getLogger(__name__)


def configure_openapi_security(app: FastAPI) -> None:
    """Configure OpenAPI security schemes for OAuth2 authentication in Swagger UI.

    Adds OAuth2 Authorization Code flow for browser-based authentication
    via Keycloak. Users click "Authorize" in Swagger UI, login via Keycloak,
    and the access token is automatically included in API requests.

    Args:
        app: FastAPI application instance
    """
    # Read Keycloak settings from environment
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8041")
    keycloak_realm = os.getenv("KEYCLOAK_REALM", "aix")
    keycloak_client_id = os.getenv("KEYCLOAK_CLIENT_ID", "lcm-public")

    def custom_openapi() -> dict[str, Any]:
        """Generate custom OpenAPI schema with security configurations."""
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        # Add security scheme for OAuth2 Authorization Code Flow
        if "components" not in openapi_schema:
            openapi_schema["components"] = {}
        if "securitySchemes" not in openapi_schema["components"]:
            openapi_schema["components"]["securitySchemes"] = {}

        openapi_schema["components"]["securitySchemes"]["oauth2"] = {
            "type": "oauth2",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/auth",
                    "tokenUrl": f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token",
                    "scopes": {
                        "openid": "OpenID Connect",
                        "profile": "User profile",
                        "email": "Email address",
                        "roles": "User roles",
                    },
                }
            },
        }

        app.openapi_schema = openapi_schema
        logger.info(f"OpenAPI security configured (Keycloak: {keycloak_url}/realms/{keycloak_realm})")
        return openapi_schema

    app.openapi = custom_openapi

    # Configure Swagger UI OAuth2 settings
    app.swagger_ui_init_oauth = {
        "clientId": keycloak_client_id,
        "usePkceWithAuthorizationCodeGrant": True,
        "scopes": "openid profile email roles",
    }
