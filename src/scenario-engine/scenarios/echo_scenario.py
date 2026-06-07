"""EchoScenario — test utility that echoes input as output.

Used for integration testing and validating the job execution pipeline.
"""

import asyncio

from application.services.scenario_context import ScenarioContext
from application.services.scenario_registry import ScenarioResult, scenario


@scenario(name="echo", version="v1", description="Echo input as output (test utility)")
class EchoScenario:
    """Simple scenario that returns input_data as output_data."""

    input_schema = {"type": "object"}
    output_schema = {"type": "object"}

    async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
        """Execute the echo scenario — sleep briefly, report progress, return input."""
        await asyncio.sleep(0.1)
        await context.report_progress(50, "Processing...")
        await asyncio.sleep(0.1)
        return ScenarioResult.completed(output_data=input_data)
