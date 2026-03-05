"""Scheduling stress test scenarios.

This module provides load testing scenarios focused on the scheduler:
- Concurrent instance creation to stress scheduling decisions
- Worker assignment latency measurement
- Scaling trigger scenarios
"""

import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, events, task

# Configuration
AUTH_TOKEN = os.environ.get("LCM_AUTH_TOKEN", "")
DEFINITION_ID = os.environ.get("LCM_DEFINITION_ID", "test-definition")


def generate_immediate_timeslot():
    """Generate a timeslot starting soon to trigger immediate scheduling."""
    now = datetime.now(timezone.utc)
    # Start in 5-30 minutes to trigger immediate scheduling
    start = now + timedelta(minutes=random.randint(5, 30))
    end = start + timedelta(hours=2)
    return start.isoformat(), end.isoformat()


def generate_future_timeslot():
    """Generate a timeslot in the future."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=random.randint(1, 7))
    end = start + timedelta(hours=random.randint(1, 4))
    return start.isoformat(), end.isoformat()


class SchedulingStressUser(HttpUser):
    """User that stresses the scheduling system.

    Creates instances with immediate timeslots to force scheduling decisions.
    Monitors scheduling latency and worker assignment.
    """

    wait_time = between(1, 3)

    created_instances: list[tuple[str, float]] = []  # (instance_id, creation_time)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.created_instances = []

    def on_start(self):
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"

    @task(5)
    def create_immediate_instance(self):
        """Create instance that needs immediate scheduling.

        Weight: 5 (high priority - main stress test)
        """
        timeslot_start, timeslot_end = generate_immediate_timeslot()

        payload = {
            "definition_id": DEFINITION_ID,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
            "owner_id": f"sched-stress-{uuid.uuid4().hex[:8]}",
            "metadata": {
                "test_type": "scheduling_stress",
                "priority": "immediate",
            },
        }

        creation_time = time.time()

        with self.client.post(
            "/api/instances",
            json=payload,
            name="[Sched] Create Immediate Instance",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                data = response.json()
                instance_id = data.get("id")
                if instance_id:
                    self.created_instances.append((instance_id, creation_time))
                    # Keep only last 50 instances
                    if len(self.created_instances) > 50:
                        self.created_instances.pop(0)
                response.success()
            else:
                response.failure(f"Create failed: {response.status_code}")

    @task(3)
    def check_scheduling_latency(self):
        """Check how long instances take to get scheduled.

        Weight: 3 (medium priority - monitoring)
        """
        if not self.created_instances:
            return

        # Check oldest unscheduled instance
        instance_id, creation_time = self.created_instances[0]

        with self.client.get(
            f"/api/instances/{instance_id}",
            name="[Sched] Check Scheduling Status",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                state = data.get("state", "unknown")

                if state in ("scheduled", "running", "instantiating"):
                    # Calculate scheduling latency
                    latency = time.time() - creation_time

                    # Report custom metric
                    events.request.fire(
                        request_type="SCHEDULING",
                        name="Scheduling Latency",
                        response_time=latency * 1000,  # ms
                        response_length=0,
                        response=None,
                        context={},
                        exception=None,
                    )

                    # Remove from tracking
                    self.created_instances.pop(0)

                    # Check against SLA (5 seconds)
                    if latency > 5:
                        response.failure(f"Scheduling SLA exceeded: {latency:.2f}s")
                    else:
                        response.success()
                elif state == "pending":
                    # Still waiting
                    response.success()
                else:
                    response.success()
            elif response.status_code == 404:
                # Instance no longer exists
                self.created_instances.pop(0)
                response.success()
            else:
                response.failure(f"Check failed: {response.status_code}")

    @task(2)
    def query_pending_instances(self):
        """Query pending instances to monitor queue depth.

        Weight: 2 (monitoring)
        """
        with self.client.get(
            "/api/instances",
            params={"state": "pending", "size": 100},
            name="[Sched] Query Pending Queue",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                pending_count = len(data) if isinstance(data, list) else 0

                # Report custom metric for queue depth
                events.request.fire(
                    request_type="METRIC",
                    name="Pending Queue Depth",
                    response_time=pending_count,  # Abuse response_time for gauge
                    response_length=0,
                    response=None,
                    context={},
                    exception=None,
                )

                response.success()
            else:
                response.failure(f"Query failed: {response.status_code}")

    @task(1)
    def query_worker_availability(self):
        """Check worker availability and capacity.

        Weight: 1 (admin monitoring)
        """
        with self.client.get(
            "/api/workers",
            name="[Sched] Check Worker Availability",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                workers = response.json()
                if isinstance(workers, list):
                    running_workers = sum(1 for w in workers if w.get("state") == "running")

                    # Report worker availability metric
                    events.request.fire(
                        request_type="METRIC",
                        name="Running Workers",
                        response_time=running_workers,
                        response_length=0,
                        response=None,
                        context={},
                        exception=None,
                    )
                response.success()
            else:
                response.failure(f"Workers query failed: {response.status_code}")


class ConcurrentSchedulingUser(HttpUser):
    """User that creates many instances concurrently.

    Tests scheduler's ability to handle burst loads.
    """

    wait_time = between(0.1, 0.5)  # Very fast - burst mode
    weight = 2

    def on_start(self):
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"

    @task
    def burst_create(self):
        """Create instances as fast as possible."""
        timeslot_start, timeslot_end = generate_immediate_timeslot()

        payload = {
            "definition_id": DEFINITION_ID,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
            "owner_id": f"burst-{uuid.uuid4().hex[:8]}",
        }

        self.client.post(
            "/api/instances",
            json=payload,
            name="[Burst] Rapid Instance Create",
        )


class ScaleUpTriggerUser(HttpUser):
    """User that creates instances requiring worker scale-up.

    Creates many instances for the same timeslot to exhaust worker capacity.
    """

    wait_time = between(2, 5)
    weight = 1

    # Shared timeslot for all instances to force capacity issues
    shared_timeslot: tuple[str, str] = None

    def on_start(self):
        if AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
        self.client.headers["Accept"] = "application/json"
        self.client.headers["Content-Type"] = "application/json"

        # Generate a shared timeslot
        if not self.shared_timeslot:
            self.shared_timeslot = generate_immediate_timeslot()

    @task(3)
    def create_overlapping_instance(self):
        """Create instances with same timeslot to force capacity limits."""
        if not self.shared_timeslot:
            self.shared_timeslot = generate_immediate_timeslot()

        timeslot_start, timeslot_end = self.shared_timeslot

        payload = {
            "definition_id": DEFINITION_ID,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
            "owner_id": f"overlap-{uuid.uuid4().hex[:8]}",
            "metadata": {
                "test_type": "scale_trigger",
            },
        }

        self.client.post(
            "/api/instances",
            json=payload,
            name="[Scale] Overlapping Instance",
        )

    @task(1)
    def rotate_timeslot(self):
        """Occasionally rotate to a new timeslot."""
        self.shared_timeslot = generate_immediate_timeslot()
