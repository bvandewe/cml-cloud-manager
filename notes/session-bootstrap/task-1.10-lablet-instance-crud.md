# Session Bootstrap: Task 1.10 - LabletInstance CRUD Commands/Queries

> **Purpose:** Paste this prompt at session start to accelerate context gathering and output quality.

---

## IMMEDIATE ACTIONS

1. **Recall session context:**

   ```
   mcp_knowledge_recall_session(workspace_id="lablet-cloud-manager", focus_hint="CQRS commands queries LabletInstance scheduling")
   ```

2. **Set focus:**

   ```
   mcp_knowledge_set_focus(
     workspace_id="lablet-cloud-manager",
     name="Task 1.10: LabletInstance CRUD",
     description="Implement CQRS commands and queries for LabletInstance aggregate",
     active_plan="docs/implementation/phase-1-foundation.md",
     current_phase="Week 4: CRUD APIs",
     priority_files=[
       "application/commands/lablet_instance/create_lablet_instance_command.py",
       "application/queries/get_lablet_instance_query.py",
       "domain/entities/lablet_instance.py",
       "domain/repositories/lablet_instance_repository.py"
     ],
     priority_components=["LabletInstance", "Mediator", "CommandHandler", "QueryHandler"]
   )
   ```

---

## TASK CONTEXT

**From Phase 1 Plan (docs/implementation/phase-1-foundation.md):**

### Task 1.10: LabletInstance CRUD Commands/Queries (2 days)

**Files to Create:**

```
src/control-plane-api/application/commands/lablet_instance/create_lablet_instance_command.py
src/control-plane-api/application/commands/lablet_instance/terminate_lablet_instance_command.py
src/control-plane-api/application/queries/get_lablet_instance_query.py
src/control-plane-api/application/queries/list_lablet_instances_query.py
src/control-plane-api/application/dtos/lablet_instance_dto.py
```

**Acceptance Criteria:**

- [ ] CreateLabletInstanceCommand (reservation request)
- [ ] TerminateLabletInstanceCommand
- [ ] GetLabletInstanceQuery
- [ ] ListLabletInstancesQuery (filter by state, worker, owner)
- [ ] DTOs for API responses
- [ ] Unit tests for handlers

---

## REFERENCE PATTERNS

### 1. Just-Completed Task 1.9 (Use as Primary Reference)

The LabletDefinition CRUD implementation follows identical patterns:

- `application/commands/lablet_definition/create_lablet_definition_command.py`
- `application/queries/get_lablet_definition_query.py`
- `application/queries/list_lablet_definitions_query.py`
- `application/dtos/lablet_definition_dto.py`

### 2. Self-Contained Command Pattern

```python
@dataclass
class CreateLabletInstanceCommand(Command[OperationResult[LabletInstanceCreatedDto]]):
    lablet_definition_id: str
    owner_id: str
    # ... fields

class CreateLabletInstanceCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateLabletInstanceCommand, OperationResult[LabletInstanceCreatedDto]]
):
    def __init__(self, mediator, mapper, cloud_event_bus, cloud_event_publishing_options,
                 lablet_instance_repository: LabletInstanceRepository,
                 lablet_definition_repository: LabletDefinitionRepository):
        # ...

    async def handle_async(self, request, cancellation_token=None):
        # Validate using self.bad_request(), self.not_found(), etc.
        # Verify definition exists
        # Create instance via LabletInstance.create()
        # Save to repository
        # Return self.created(dto)
```

---

## CRITICAL PATTERNS TO FOLLOW

### Handler Helper Methods (from RequestHandler base)

```python
# Success responses
return self.ok(data)           # 200 OK
return self.created(data)      # 201 Created
return self.accepted(data)     # 202 Accepted
return self.no_content()       # 204 No Content

# Error responses
return self.bad_request("message")              # 400
return self.not_found("Resource", "detail")     # 404
return self.conflict("message")                 # 409
return self.unprocessable_entity("message")     # 422
```

### Mediator Usage

```python
# ✅ CORRECT - Single argument only
result = await self.mediator.execute_async(GetLabletInstanceQuery(id="123"))

# ❌ WRONG - Never pass cancellation_token to mediator
result = await self.mediator.execute_async(query, cancellation_token)
```

### OperationResult Checking

```python
if result.is_success:  # NOT is_successful
    data = result.data  # NOT content
else:
    error = result.error_message  # NOT errors
```

---

## LABLETINSTANCE DOMAIN CONTEXT

### Entity Location

- `domain/entities/lablet_instance.py` - Aggregate with AggregateState pattern
- `domain/events/lablet_instance_events.py` - Domain events
- `domain/repositories/lablet_instance_repository.py` - Repository interface

### Key Fields (from LabletInstanceState - READ THESE FILES FIRST)

```python
id: str
lablet_definition_id: str
owner_id: str
status: LabletInstanceStatus  # PENDING, SCHEDULED, INSTANTIATING, RUNNING, etc.
assigned_worker_id: str | None
assigned_ports: dict[str, int] | None
cml_lab_id: str | None
session_token: str | None
expires_at: datetime | None
created_at: datetime
started_at: datetime | None
terminated_at: datetime | None
```

### Status Enum (from domain/enums.py)

```python
class LabletInstanceStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    INSTANTIATING = "instantiating"
    RUNNING = "running"
    COLLECTING = "collecting"
    GRADING = "grading"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    TERMINATED = "terminated"
```

---

## SUGGESTED IMPLEMENTATION ORDER

1. **Create DTOs first** (`application/dtos/lablet_instance_dto.py`)
   - LabletInstanceDto (full response)
   - LabletInstanceSummaryDto (for lists)
   - LabletInstanceCreatedDto (for create response)

2. **Create GetLabletInstanceQuery** (simplest query)
   - By id
   - Return LabletInstanceDto or not_found

3. **Create ListLabletInstancesQuery** (with pagination and filters)
   - Filters: status, worker_id, owner_id, lablet_definition_id
   - Pagination: skip, limit
   - Return list of LabletInstanceSummaryDto

4. **Create CreateLabletInstanceCommand**
   - Validate required fields
   - Verify LabletDefinition exists
   - Create instance via LabletInstance.create() (PENDING status)
   - Save to repository
   - Return LabletInstanceCreatedDto

5. **Create TerminateLabletInstanceCommand**
   - Find instance by id
   - Check current status allows termination
   - Call instance.terminate() or appropriate domain method
   - Update repository
   - Return success or error

---

## FILES TO READ FOR CONTEXT

```bash
# Domain entities and events (READ FIRST - understand the aggregate)
read_file domain/entities/lablet_instance.py 1 300
read_file domain/events/lablet_instance_events.py 1 150

# Repository interface
read_file domain/repositories/lablet_instance_repository.py 1 100

# Reference implementation from Task 1.9 (COPY PATTERNS FROM HERE)
read_file application/commands/lablet_definition/create_lablet_definition_command.py 1 200
read_file application/queries/get_lablet_definition_query.py 1 80
read_file application/queries/list_lablet_definitions_query.py 1 100
read_file application/dtos/lablet_definition_dto.py 1 200

# Status enum
read_file domain/enums.py 70 100
```

---

## VALIDATION CHECKLIST

After implementation, verify:

- [ ] All commands/queries are self-contained (request + handler in same file)
- [ ] Commands in `application/commands/lablet_instance/` folder
- [ ] Queries in `application/queries/` folder (flat)
- [ ] Handlers use helper methods (self.ok, self.bad_request, etc.)
- [ ] DTOs are dataclasses with proper type hints
- [ ] Unit tests cover success and error paths
- [ ] No inline imports inside methods (all at module level)
- [ ] Exports added to `application/commands/__init__.py`
- [ ] Exports added to `application/queries/__init__.py`
- [ ] Exports added to `application/dtos/__init__.py`

---

## QUICK COMMANDS

```bash
# Run tests for new files
cd src/control-plane-api && .venv/bin/python -m pytest tests/application/test_lablet_instance_crud.py -v

# Check for errors
cd src/control-plane-api && .venv/bin/python -m ruff check application/commands/lablet_instance/ application/queries/get_lablet_instance_query.py application/queries/list_lablet_instances_query.py application/dtos/lablet_instance_dto.py

# Verify imports
cd src/control-plane-api && .venv/bin/python -c "from application.commands import CreateLabletInstanceCommand; print('OK')"
```

---

**Ready to start Task 1.10!**
