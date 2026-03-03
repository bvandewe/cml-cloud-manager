import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from api.services.auth import DualAuthService
from application.settings import app_settings
from domain.repositories.cml_worker_repository import CMLWorkerRepository  # noqa: F401

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


class SystemHealthService:
    """Aggregates system health checks.

    Extracted from `SystemController` to reduce controller size.
    """

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:  # type: ignore[name-defined]
        builder.services.add_singleton(SystemHealthService)
        logging.getLogger(__name__).info("✅ SystemHealthService configured as singleton")

    async def get_system_health(self, mediator, service_provider) -> dict[str, Any]:
        """Run all health checks and return aggregated result."""
        import asyncio

        health_status: dict[str, Any] = {"status": "healthy", "components": {}}

        # Database (Mongo) check via simple query
        try:
            from application.queries.get_cml_workers_query import GetCMLWorkersQuery
            from integration.enums import AwsRegion

            t0 = time.perf_counter()
            query = GetCMLWorkersQuery(aws_region=AwsRegion.US_EAST_1)
            _ = await mediator.execute_async(query)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            health_status["components"]["database"] = {
                "status": "healthy",
                "type": "mongodb",
                "latency_ms": latency_ms,
            }
        except Exception as e:
            log.error(f"Database health check failed: {e}")
            health_status["components"]["database"] = {
                "status": "unhealthy",
                "error": str(e),
                "latency_ms": None,
            }
            health_status["status"] = "degraded"

        # Session / Redis store
        try:
            auth_service: DualAuthService = service_provider.get_required_service(DualAuthService)  # type: ignore
            store = getattr(auth_service, "session_store", None)
            if store is None:
                health_status["components"]["redis"] = {
                    "status": "unhealthy",
                    "error": "session store missing",
                    "latency_ms": None,
                }
                health_status["status"] = "degraded"
            else:
                # Try ping if available (Redis); otherwise mark in-memory
                if hasattr(store, "ping"):
                    t0 = time.perf_counter()
                    ok = store.ping()
                    latency_ms = (time.perf_counter() - t0) * 1000.0
                    health_status["components"]["redis"] = {
                        "status": "healthy" if ok else "unhealthy",
                        "backend": "redis",
                        "latency_ms": latency_ms if ok else None,
                        "url": app_settings.redis_url,
                    }
                    if not ok:
                        health_status["status"] = "degraded"
                else:
                    health_status["components"]["redis"] = {
                        "status": "healthy",
                        "backend": "in-memory",
                        "latency_ms": 0,
                    }
        except Exception as e:
            log.error(f"Redis/session store health check failed: {e}")
            health_status["components"]["redis"] = {
                "status": "error",
                "error": str(e),
                "latency_ms": None,
            }
            health_status["status"] = "degraded"

        # CloudEvent sink
        try:
            sink = app_settings.cloud_event_sink
            if sink:
                async with httpx.AsyncClient(timeout=5) as client:
                    event_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    ce_source = app_settings.cloud_event_source or "https://lablet-cloud-manager.io"
                    cloudevent_body = {
                        "specversion": "1.0",
                        "id": event_id,
                        "time": now,
                        "datacontenttype": "application/json",
                        "type": f"{app_settings.cloud_event_type_prefix}.healthcheck.v1",
                        "source": ce_source,
                        "subject": "healthcheck",
                        "data": {"ping": "healthcheck", "timestamp": now},
                    }
                    headers = {"Content-Type": "application/cloudevents+json"}
                    t0 = time.perf_counter()
                    resp = await client.post(sink, json=cloudevent_body, headers=headers)
                    latency_ms = (time.perf_counter() - t0) * 1000.0
                    if 200 <= resp.status_code < 300:
                        health_status["components"]["cloudevent_sink"] = {
                            "status": "healthy",
                            "endpoint": sink,
                            "event_id": event_id,
                            "latency_ms": latency_ms,
                        }
                    else:
                        health_status["components"]["cloudevent_sink"] = {
                            "status": "unhealthy",
                            "endpoint": sink,
                            "code": resp.status_code,
                            "event_id": event_id,
                            "latency_ms": latency_ms,
                        }
                        health_status["status"] = "degraded"
            else:
                health_status["components"]["cloudevent_sink"] = {
                    "status": "disabled",
                    "latency_ms": None,
                }
        except Exception as e:
            log.error(f"CloudEvent sink health check failed: {e}")
            health_status["components"]["cloudevent_sink"] = {
                "status": "error",
                "error": str(e),
                "latency_ms": None,
            }
            health_status["status"] = "degraded"

        # Keycloak
        try:
            keycloak_base = app_settings.keycloak_url_internal or app_settings.keycloak_url
            realm = app_settings.keycloak_realm
            openid_config = f"{keycloak_base}/realms/{realm}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=5) as client:
                t0 = time.perf_counter()
                resp = await client.get(openid_config)
                latency_ms = (time.perf_counter() - t0) * 1000.0
            if resp.status_code == 200:
                issuer = resp.json().get("issuer") if resp.headers.get("content-type", "").startswith("application/json") else None
                health_status["components"]["keycloak"] = {
                    "status": "healthy",
                    "realm": realm,
                    "issuer": issuer,
                    "latency_ms": latency_ms,
                }
            else:
                health_status["components"]["keycloak"] = {
                    "status": "unhealthy",
                    "realm": realm,
                    "code": resp.status_code,
                    "latency_ms": latency_ms,
                }
                health_status["status"] = "degraded"
        except Exception as e:
            log.error(f"Keycloak health check failed: {e}")
            health_status["components"]["keycloak"] = {
                "status": "error",
                "error": str(e),
                "latency_ms": None,
            }
            health_status["status"] = "degraded"

        # OTEL collector
        try:
            if app_settings.otel_enabled and app_settings.otel_endpoint:
                endpoint = app_settings.otel_endpoint
                host_port = endpoint.replace("http://", "").replace("https://", "")
                host, port_str = host_port.split(":", 1)
                port = int(port_str)
                t0 = time.perf_counter()
                fut = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(fut, timeout=3)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    log.warning("failed writing to OTEL collector connection", exc_info=True)
                health_status["components"]["otel_collector"] = {
                    "status": "healthy",
                    "endpoint": endpoint,
                    "latency_ms": latency_ms,
                }
            else:
                health_status["components"]["otel_collector"] = {
                    "status": "disabled",
                    "latency_ms": None,
                }
        except Exception as e:
            log.error(f"OTEL collector health check failed: {e}")
            health_status["components"]["otel_collector"] = {
                "status": "error",
                "error": str(e),
                "latency_ms": None,
            }
            health_status["status"] = "degraded"

        # Controller microservices (server-side checks, no CORS issue)
        controller_services = {
            "worker_controller": app_settings.worker_controller_url,
            "lablet_controller": app_settings.lablet_controller_url,
            "resource_scheduler": app_settings.resource_scheduler_url,
        }

        async def check_controller(name: str, base_url: str) -> tuple[str, dict[str, Any]]:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    t0 = time.perf_counter()
                    resp = await client.get(f"{base_url}/api/health")
                    latency_ms = (time.perf_counter() - t0) * 1000.0
                    if resp.status_code == 200:
                        return name, {
                            "status": "healthy",
                            "endpoint": f"{base_url}/api/health",
                            "latency_ms": latency_ms,
                        }
                    else:
                        return name, {
                            "status": "unhealthy",
                            "endpoint": f"{base_url}/api/health",
                            "code": resp.status_code,
                            "latency_ms": latency_ms,
                        }
            except Exception as e:
                log.warning(f"{name} health check failed: {e}")
                return name, {
                    "status": "unavailable",
                    "endpoint": f"{base_url}/api/health",
                    "error": str(e),
                    "latency_ms": None,
                }

        controller_results = await asyncio.gather(*[check_controller(name, url) for name, url in controller_services.items()])
        for name, result in controller_results:
            health_status["components"][name] = result
            if result["status"] != "healthy":
                health_status["status"] = "degraded"

        return health_status
