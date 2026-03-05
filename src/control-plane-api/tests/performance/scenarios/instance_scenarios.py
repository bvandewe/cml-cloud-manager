"""Instance-focused load testing scenarios.

This module provides specialized load testing for instance lifecycle operations:
- High-volume instance creation
- Concurrent scheduling
- Instance state transitions
- Pagination performance
"""

import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, SequentialTaskSet, between, task

# Configuration
AUTH_TOKEN = os.environ.get("LCM_AUTH_TOKEN", "")
DEFINITION_ID = os.environ.get("LCM_DEFINITION_ID", "test-definition")


def generate_timeslot():
    """Generate a future timeslot."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=random.randint(1, 168))
    end = start + timedelta(hours=random.randint(1, 4))
    return start.isoformat(), end.isoformat()


class InstanceLifecycleSequence(SequentialTaskSet):
    """Sequential task set for complete instance lifecycle.

    Executes operations in order:
    1. Create instance
    2. Wait for scheduling
    3. Check status multiple times
    4. Terminate instance
    """

    instance_id: str = None

    @task
    def create_instance(self):
        """Step 1: Create a new instance."""
        timeslot_start, timeslot_end = generate_timeslot()

        payload = {
            "definition_id": DEFINITION_ID,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
            "owner_id": f"lifecycle-test-{uuid.uuid4().hex[:8]}",
        }

        with self.client.post(
            "/api/instances",
            json=payload,
            name="[Lifecycle] Create Instance",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                data = response.json()
                self.instance_id = data.get("id")
                response.success()
            else:
                response.failure(f"Failed to create: {response.status_code}")
                self.interrupt()  # Skip remaining tasks

    @task
    def check_scheduled(self):
        """Step 2: Check if instance is scheduled."""
        if not self.instance_id:
            self.interrupt()
            return

        # Poll a few times with short delays
        for _ in range(3):
            with self.client.get(
                f"/api/instances/{self.instance_id}",
                name="[Lifecycle] Check Scheduling",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    data = response.json()
                    state = data.get("state", "unknown")
                    if state in ("scheduled", "running", "instantiating"):
                        response.success()
                        return
                    response.success()  # Still pending, but valid
                else:
                    response.failure(f"Check failed: {response.status_code}")

    @task
    def get_instance_details(self):
        """Step 3: Get full instance details."""
        if not self.instance_id:
            self.interrupt()
            return

        with self.client.get(
            f"/api/instances/{self.instance_id}",
            name="[Lifecycle] Get Details",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Details failed: {response.status_code}")

    @task
    def terminate_instance(self):
        """Step 4: Terminate the instance."""
        if not self.instance_id:
            self.interrupt()
            return

        with self.client.delete(
            f"/api/instances/{self.instance_id}",
            name="[Lifecycle] Terminate",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 202, 404):
                response.success()
            else:
                response.failure(f"Terminate failed: {response.status_code}")

        # Clear instance ID and stop the sequence
        self.instance_id = None
        self.interrupt()


class InstanceBurstUser(HttpUser):
    """User that creates instances in bursts.

    Simulates batch operations where many instances are created quickly.
    """

    wait_time = between(0.5, 1.5)  # Fast operations
    weight = 2

    def on_start(self):
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"

    @task(5)
    def burst_create(self):
        """Create instances rapidly."""
        timeslot_start, timeslot_end = generate_timeslot()

        payload = {
            "definition_id": DEFINITION_ID,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
            "owner_id": f"burst-{uuid.uuid4().hex[:8]}",
        }

        self.client.post(
            "/api/instances",
            json=payload,
            name="[Burst] Create Instance",
        )

    @task(1)
    def query_pending(self):
        """Query pending instances."""
        self.client.get(
            "/api/instances",
            params={"state": "pending", "size": 50},
            name="[Burst] Query Pending",
        )


class InstanceQueryUser(HttpUser):
    """User focused on reading/querying instances.

    Simulates read-heavy workload with various query patterns.
    """

    wait_time = between(1, 3)
    weight = 3  # Most common user type

    def on_start(self):
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"

    @task(5)
    def paginated_list(self):
        """List instances with pagination."""
        page = random.randint(1, 20)
        size = random.choice([10, 25, 50])

        self.client.get(
            "/api/instances",
            params={"page": page, "size": size},
            name="[Query] Paginated List",
        )

    @task(3)
    def filter_by_state(self):
        """Filter instances by state."""
        state = random.choice(["pending", "scheduled", "running", "stopped"])

        self.client.get(
            "/api/instances",
            params={"state": state, "size": 25},
            name="[Query] Filter by State",
        )

    @task(2)
    def filter_by_definition(self):
        """Filter instances by definition."""
        self.client.get(
            "/api/instances",
            params={"definition_id": DEFINITION_ID, "size": 25},
            name="[Query] Filter by Definition",
        )

    @task(1)
    def combined_filters(self):
        """Use multiple filters."""
        state = random.choice(["pending", "scheduled", "running"])

        self.client.get(
            "/api/instances",
            params={
                "state": state,
                "definition_id": DEFINITION_ID,
                "size": 50,
            },
            name="[Query] Combined Filters",
        )


class InstanceLifecycleUser(HttpUser):
    """User that executes full instance lifecycles."""

    wait_time = between(2, 5)
    tasks = [InstanceLifecycleSequence]
    weight = 1

    def on_start(self):
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"
