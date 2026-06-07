"""Placeholder for scenario implementations.

Scenarios are registered via the @scenario decorator from
application.services.scenario_registry.

Example:

    from application.services.scenario_registry import scenario, ScenarioResult

    @scenario(name="lab_resolve", version="v1", description="Resolve a CML lab topology")
    class LabResolveScenario:
        input_schema = {
            "type": "object",
            "properties": {
                "worker_id": {"type": "string"},
                "lab_definition_uri": {"type": "string"},
            },
            "required": ["worker_id", "lab_definition_uri"],
        }
        output_schema = {
            "type": "object",
            "properties": {
                "lab_id": {"type": "string"},
                "topology": {"type": "object"},
            },
        }

        async def execute(self, input_data, context):
            # Implementation goes here
            return ScenarioResult.completed({"lab_id": "..."})
"""
