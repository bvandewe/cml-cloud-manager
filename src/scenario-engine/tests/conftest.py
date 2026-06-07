"""Test fixtures for Scenario Engine."""

import pytest


@pytest.fixture
def sample_job_input():
    """Sample job submission input."""
    return {
        "scenario_name": "lab_resolve",
        "scenario_version": "v1",
        "input_data": {"worker_id": "w-123", "lab_definition_uri": "s3://bucket/lab.zip"},
        "callback_url": "http://lcm/api/v1/events",
    }
