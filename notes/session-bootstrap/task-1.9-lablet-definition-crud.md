# Session Bootstrap: Task 1.9 - LabletDefinition CRUD Commands/Queries

> **Purpose:** Paste this prompt at session start to accelerate context gathering.

---

## IMMEDIATE ACTIONS

1. **Recall session context:**

   ```
   mcp_knowledge_recall_session(workspace_id="lablet-cloud-manager", focus_hint="CQRS commands queries LabletDefinition")
   ```

2. **Set focus:**

   ```
   mcp_knowledge_set_focus(
     workspace_id="lablet-cloud-manager",
     name="Task 1.9: LabletDefinition CRUD",
     description="Implement CQRS commands and queries for LabletDefinition aggregate",
     active_plan="docs/implementation/phase-1-foundation.md",
     current_phase="Week 4: CRUD APIs",
     priority_files=[
       "application/commands/create_lablet_definition_command.py",
       "application/queries/get_lablet_definition_query.py",
       "domain/entities/lablet_definition.py",
       "domain/repositories/lablet_definition_repository.py"
     ],
     priority_components=["LabletDefinition", "Mediator", "CommandHandler", "QueryHandler"]
   )
   ```

---

## TASK CONTEXT

**From Phase 1 Plan (docs/implementation/phase-1-foundation.md, lines 290-340):**

### Task 1.9: LabletDefinition CRUD Commands/Queries (2 days)

**Files to Create:**

```
src/application/commands/create_lablet_definition_command.py
src/application/commands/sync_lablet_definition_command.py
src/application/queries/get_lablet_definition_query.py
src/application/queries/list_lablet_definitions_query.py
src/application/dtos/lablet_definition_dto.py
```

**Acceptance Criteria:**

- [ ] CreateLabletDefinitionCommand with validation
- [ ] SyncLabletDefinitionCommand (trigger artifact sync)
- [ ] GetLabletDefinitionQuery (by id, by name+version)
- [ ] ListLabletDefinitionsQuery (with pagination, filters)
- [ ] DTOs for API responses
- [ ] Unit tests for handlers

---

## REFERENCE PATTERNS

### 1. Self-Contained Command Pattern

Read existing examples:

- `application/commands/create_task_command.py` - Basic command pattern
- `application/commands/create_lab_record_command.py` - Domain entity creation

**Key Pattern:**

```python
@dataclass
class CreateLabletDefinitionCommand(Command[OperationResult[LabletDefinitionCreatedDto]]):
    name: str
    version: str
    lab_artifact_uri: str
    # ... fields

class CreateLabletDefinitionCommandHandler(CommandHandler[CreateLabletDefinitionCommand, OperationResult[LabletDefinitionCreatedDto]]):
    def __init__(self, repository: LabletDefinitionRepository):
        self._repository = repository

    async def handle_async(self, request, cancellation_token=None):
        # Validate using self.bad_request(), self.conflict(), etc.
        # Create entity
        # Save via repository
        # Return self.created(dto)
```

### 2. Self-Contained Query Pattern

Read existing examples:

- `application/queries/get_task_query.py` - Single entity query
- `application/queries/list_cml_workers_query.py` - List with filters

### 3. DTO Pattern

Read existing examples:

- `application/dtos/task_dto.py` - Basic DTO
- `application/dtos/cml_worker_dto.py` - Complex DTO with nested objects

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
result = await self.mediator.execute_async(GetLabletDefinitionQuery(id="123"))

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

## LABLETDEFINITION DOMAIN CONTEXT

### Entity Location

- `domain/entities/lablet_definition.py` - Aggregate with AggregateState pattern
- `domain/events/lablet_definition_events.py` - Domain events (Created, VersionCreated, Deprecated, etc.)
- `domain/repositories/lablet_definition_repository.py` - Repository interface
- `integration/repositories/mongo_lablet_definition_repository.py` - MongoDB implementation

### Key Fields (from LabletDefinitionState)

```python
id: str
name: str
version: str  # Semantic version
lab_artifact_uri: str
lab_yaml_hash: str
lab_yaml_cached: str | None
resource_requirements: ResourceRequirements
license_affinity: list[LicenseType]
node_count: int
port_template: PortTemplate
grading_rules_uri: str | None
max_duration_minutes: int
warm_pool_depth: int
owner_notification: dict | None
is_deprecated: bool
created_by: str
created_at: datetime
```

### Value Objects to Use

- `domain/value_objects/resource_requirements.py` - CPU/memory/storage requirements
- `domain/value_objects/port_template.py` - Port mapping configuration
- `domain/enums/license_type.py` - PERSONAL, ENTERPRISE, EVALUATION

---

## SUGGESTED IMPLEMENTATION ORDER

1. **Create DTOs first** (`application/dtos/lablet_definition_dto.py`)
   - LabletDefinitionDto (full response)
   - LabletDefinitionSummaryDto (for lists)
   - LabletDefinitionCreatedDto (for create response)

2. **Create GetLabletDefinitionQuery** (simplest query)
   - By id
   - Return LabletDefinitionDto or not_found

3. **Create ListLabletDefinitionsQuery** (with pagination)
   - Filters: name, version, is_deprecated
   - Pagination: skip, limit
   - Return list of LabletDefinitionSummaryDto

4. **Create CreateLabletDefinitionCommand**
   - Validate required fields
   - Check for duplicate name+version
   - Create entity via LabletDefinition.create()
   - Save to repository
   - Return LabletDefinitionCreatedDto

5. **Create SyncLabletDefinitionCommand**
   - Fetch lab artifact from URI
   - Parse YAML, compute hash
   - Update cached content and hash
   - Return sync status

---

## FILES TO READ FOR CONTEXT

```bash
# Domain entities and events
read_file domain/entities/lablet_definition.py 1 150
read_file domain/events/lablet_definition_events.py 1 100

# Repository interface
read_file domain/repositories/lablet_definition_repository.py 1 50

# Existing command/query patterns
read_file application/commands/create_task_command.py 1 100
read_file application/queries/get_task_query.py 1 80
read_file application/queries/list_cml_workers_query.py 1 100

# Existing DTOs
read_file application/dtos/task_dto.py 1 50
```

---

## VALIDATION CHECKLIST

After implementation, verify:

- [ ] All commands/queries are self-contained (request + handler in same file)
- [ ] Handlers use helper methods (self.ok, self.bad_request, etc.)
- [ ] DTOs are dataclasses with proper type hints
- [ ] Unit tests cover success and error paths
- [ ] No inline imports inside methods (all at module level)
- [ ] Commands registered via Mediator.configure() in main.py (auto-discovered)

---

## QUICK COMMANDS

```bash
# Run tests for new files
make test PYTEST_ARGS="tests/application/commands/test_create_lablet_definition_command.py -v"

# Check for errors
make lint

# Verify imports
python -c "from application.commands.create_lablet_definition_command import CreateLabletDefinitionCommand; print('OK')"
```

---

**Ready to start Task 1.9!**
