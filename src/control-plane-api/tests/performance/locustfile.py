"""Main Locust load testing file for Lablet Cloud Manager API.

This file defines comprehensive load testing scenarios covering:
- Instance creation and lifecycle
- Worker management
- Definition queries
- Scheduling operations
- Assessment workflows

Usage:
    locust -f locustfile.py --host=http://localhost:8020

Environment Variables:
    LCM_AUTH_TOKEN: Bearer token for authentication
    LCM_DEFINITION_ID: Test definition ID to use
"""

import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, events, task

# Configuration from environment
AUTH_TOKEN = os.environ.get("LCM_AUTH_TOKEN", "")
DEFINITION_ID = os.environ.get("LCM_DEFINITION_ID", "test-definition")


def generate_timeslot():
    """Generate a future timeslot for instance creation."""
    now = datetime.now(timezone.utc)
    # Random start time between 1 hour and 7 days from now
    start = now + timedelta(hours=random.randint(1, 168))
    # Random duration between 1 and 4 hours
    end = start + timedelta(hours=random.randint(1, 4))
    return start.isoformat(), end.isoformat()


def generate_owner_id():
    """Generate a random owner ID."""
    return f"user-{uuid.uuid4().hex[:8]}"


class LabletAPIUser(HttpUser):
    """Simulates a typical API user interacting with Lablet Cloud Manager.

    This user class represents a realistic usage pattern where users:
    - Create lablet instances (3x weight - most common operation)
    - List and query instances (5x weight - frequent reads)
    - Get specific instance details (2x weight)
    - Manage workers (1x weight - admin operations)
    - View definitions (2x weight)
    """

    # Wait between 1-3 seconds between tasks
    wait_time = between(1, 3)

    # Track created instance IDs for later operations
    created_instances: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.created_instances = []

    def on_start(self):
        """Called when a user starts - set up authentication headers."""
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        # Accept JSON responses
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"

    # =========================================================================
    # Instance Operations (Most Common)
    # =========================================================================

    @task(3)
    def create_instance(self):
        """Create a new lablet instance.

        Weight: 3 (high frequency)
        Expected Response: 201 Created
        """
        timeslot_start, timeslot_end = generate_timeslot()

        payload = {
            "definition_id": DEFINITION_ID,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
            "owner_id": generate_owner_id(),
            "metadata": {
                "created_by": "locust_load_test",
                "test_run_id": str(uuid.uuid4())[:8],
            },
        }

        with self.client.post(
            "/api/instances",
            json=payload,
            name="/api/instances [POST]",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                data = response.json()
                instance_id = data.get("id")
                if instance_id:
                    self.created_instances.append(instance_id)
                    # Keep only last 20 instances per user to manage memory
                    if len(self.created_instances) > 20:
                        self.created_instances.pop(0)
                response.success()
            elif response.status_code == 401:
                response.failure("Authentication required")
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(5)
    def list_instances(self):
        """List lablet instances with pagination.

        Weight: 5 (most frequent - read-heavy workload)
        Expected Response: 200 OK
        """
        page = random.randint(1, 10)
        size = random.choice([10, 20, 50])

        # Random filter combinations
        filters = {}
        if random.random() > 0.5:
            filters["state"] = random.choice(["pending", "scheduled", "running"])
        if random.random() > 0.7:
            filters["definition_id"] = DEFINITION_ID

        with self.client.get(
            "/api/instances",
            params={"page": page, "size": size, **filters},
            name="/api/instances [GET]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(2)
    def get_instance_detail(self):
        """Get details of a specific instance.

        Weight: 2 (moderate frequency)
        Expected Response: 200 OK or 404 Not Found
        """
        if self.created_instances:
            instance_id = random.choice(self.created_instances)
            with self.client.get(
                f"/api/instances/{instance_id}",
                name="/api/instances/{id} [GET]",
                catch_response=True,
            ) as response:
                if response.status_code in (200, 404):
                    response.success()
                else:
                    response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def terminate_instance(self):
        """Terminate a lablet instance.

        Weight: 1 (low frequency - cleanup operation)
        Expected Response: 200 OK or 404 Not Found
        """
        if self.created_instances and random.random() > 0.7:
            instance_id = self.created_instances.pop()
            with self.client.delete(
                f"/api/instances/{instance_id}",
                name="/api/instances/{id} [DELETE]",
                catch_response=True,
            ) as response:
                if response.status_code in (200, 202, 404):
                    response.success()
                else:
                    response.failure(f"Unexpected status: {response.status_code}")

    # =========================================================================
    # Worker Operations (Admin)
    # =========================================================================

    @task(1)
    def list_workers(self):
        """List all workers.

        Weight: 1 (low frequency - admin operation)
        Expected Response: 200 OK
        """
        with self.client.get(
            "/api/workers",
            name="/api/workers [GET]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def get_worker_detail(self):
        """Get details of a specific worker.

        Weight: 1 (low frequency)
        Expected Response: 200 OK
        """
        # First get list of workers to pick one
        with self.client.get(
            "/api/workers",
            name="/api/workers [GET] for detail",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                workers = response.json()
                if workers and isinstance(workers, list) and len(workers) > 0:
                    worker_id = random.choice(workers).get("id")
                    if worker_id:
                        self.client.get(
                            f"/api/workers/{worker_id}",
                            name="/api/workers/{id} [GET]",
                        )
                response.success()

    # =========================================================================
    # Definition Operations (Read-Only)
    # =========================================================================

    @task(2)
    def list_definitions(self):
        """List lablet definitions.

        Weight: 2 (moderate frequency)
        Expected Response: 200 OK
        """
        with self.client.get(
            "/api/definitions",
            name="/api/definitions [GET]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # No definitions configured - still a valid response
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def get_definition_detail(self):
        """Get details of a specific definition.

        Weight: 1 (low frequency)
        Expected Response: 200 OK or 404 Not Found
        """
        with self.client.get(
            f"/api/definitions/{DEFINITION_ID}",
            name="/api/definitions/{id} [GET]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    # =========================================================================
    # Health Check (Background)
    # =========================================================================

    @task(1)
    def health_check(self):
        """Check API health.

        Weight: 1 (background monitoring)
        Expected Response: 200 OK
        """
        with self.client.get(
            "/health",
            name="/health [GET]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")


class AdminUser(HttpUser):
    """Simulates an admin user performing management operations.

    This user class has lower frequency and focuses on:
    - Worker management
    - System configuration
    - Bulk operations
    """

    # Admins work slower - 5-10 seconds between tasks
    wait_time = between(5, 10)

    # Lower weight - fewer admin users
    weight = 1

    def on_start(self):
        """Set up admin authentication."""
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"

    @task(2)
    def view_system_health(self):
        """View overall system health."""
        self.client.get("/health", name="/health [ADMIN]")
        self.client.get("/ready", name="/ready [ADMIN]")

    @task(1)
    def view_metrics(self):
        """View system metrics (Prometheus endpoint)."""
        with self.client.get(
            "/metrics",
            name="/metrics [ADMIN]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Metrics unavailable: {response.status_code}")

    @task(1)
    def list_all_workers(self):
        """Get comprehensive worker listing."""
        self.client.get("/api/workers", name="/api/workers [ADMIN]")

    @task(1)
    def list_all_instances(self):
        """Get comprehensive instance listing with all states."""
        self.client.get(
            "/api/instances",
            params={"size": 100},
            name="/api/instances [ADMIN - full list]",
        )


# =========================================================================
# Event Handlers for Custom Reporting
# =========================================================================


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when a load test is started."""
    print("=" * 60)
    print("LABLET CLOUD MANAGER - LOAD TEST STARTED")
    print("=" * 60)
    print(f"Target host: {environment.host}")
    print(f"Users: {environment.parsed_options.num_users if hasattr(environment.parsed_options, 'num_users') else 'TBD'}")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when a load test is stopped."""
    print("=" * 60)
    print("LABLET CLOUD MANAGER - LOAD TEST COMPLETED")
    print("=" * 60)

    # Print summary statistics
    stats = environment.stats
    if stats.total:
        print(f"Total requests: {stats.total.num_requests}")
        print(f"Failure rate: {stats.total.fail_ratio * 100:.2f}%")
        print(f"Median response time: {stats.total.median_response_time}ms")
        print(f"95th percentile: {stats.total.get_response_time_percentile(0.95)}ms")
        print(f"99th percentile: {stats.total.get_response_time_percentile(0.99)}ms")
        print(f"Requests/sec: {stats.total.current_rps:.2f}")
    print("=" * 60)


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Called on every request - can be used for custom metrics."""
    # Example: Log slow requests (> 1 second)
    if response_time > 1000:
        print(f"⚠️ Slow request: {name} took {response_time}ms")
