# Feature Request: Import Existing EC2 Instances as CML Workers

## Current State Analysis

### ✅ What Exists

1. **AWS EC2 Client (`AwsEc2Client`)** - Comprehensive EC2 integration:
   - ✅ `list_instances()` - Query instances with filters (AMI ID, instance types, states, tags)
   - ✅ `get_instance_details()` - Get detailed info about a specific instance
   - ✅ `create_instance()` - Provision new EC2 instances
   - ✅ `start/stop/terminate_instance()` - Lifecycle management
   - ✅ `get_instance_status_checks()` - Health monitoring
   - ✅ `get/add/remove_tags()` - Tag management

2. **CML Worker Entity** - Domain model with:
   - ✅ AWS instance details (instance_id, region, AMI, type)
   - ✅ Network details (public_ip, private_ip)
   - ✅ Status management (worker status, service status)
   - ✅ CML-specific attributes (version, license, endpoint)

3. **Repository Layer**:
   - ✅ `CMLWorkerRepository` - MongoDB persistence via Motor
   - ✅ Query methods: get_by_id, get_by_aws_instance_id, get_by_status, etc.

4. **Existing Commands**:
   - ✅ `CreateCMLWorkerCommand` - Create worker AND provision EC2
   - ✅ `StartCMLWorkerCommand` - Start stopped worker
   - ✅ `StopCMLWorkerCommand` - Stop running worker
   - ✅ `TerminateCMLWorkerCommand` - Terminate worker
   - ✅ `UpdateCMLWorkerStatusCommand` - Update status
   - ✅ `UpdateCMLWorkerTagsCommand` - Update tags

5. **Existing Queries**:
   - ✅ `GetCMLWorkersQuery` - List all workers
   - ✅ `GetCMLWorkerByIdQuery` - Get specific worker
   - ✅ `GetCMLWorkerResourcesQuery` - Get CloudWatch metrics

### ❌ What's Missing

**The ability to import/register existing EC2 instances that were created outside the system.**

Currently, `CreateCMLWorkerCommand` **always creates a NEW EC2 instance**. There's no command to:

- Discover existing instances in AWS
- Import/register them as CML Workers in the local database
- Associate existing instances with the management system

---

## Use Case

**Scenario:** You have EC2 instances running CML that were:

- Created manually through AWS Console
- Provisioned by CloudFormation/Terraform
- Created by another system
- Running before Lablet Cloud Manager was deployed

**Need:** Import these instances into Lablet Cloud Manager to manage them through the application.

---

## Recommended Implementation Plan

### Phase 1: Command & Handler (Backend Logic)

#### 1.1 Create New Command

**File:** `src/application/commands/import_cml_worker_command.py`

```python
"""Import existing EC2 instance as CML Worker command."""

from dataclasses import dataclass
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from integration.models import CMLWorkerInstanceDto


@dataclass
class ImportCMLWorkerCommand(Command[OperationResult[CMLWorkerInstanceDto]]):
    """Command to import an existing EC2 instance as a CML Worker.

    This command discovers an existing EC2 instance and registers it
    in the local database without creating a new instance.

    Args:
        aws_region: AWS region where the instance exists
        aws_instance_id: AWS EC2 instance ID (if known)
        ami_id: AMI ID to search for (if instance_id not provided)
        ami_name: AMI name pattern to search for (if instance_id not provided)
        name: Friendly name for the CML Worker
        created_by: User who initiated the import
    """

    aws_region: str
    aws_instance_id: str | None = None  # Direct lookup
    ami_id: str | None = None           # Search by AMI ID
    ami_name: str | None = None         # Search by AMI name
    name: str | None = None             # Override instance name
    created_by: str | None = None


class ImportCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[ImportCMLWorkerCommand, OperationResult[CMLWorkerInstanceDto]],
):
    """Handle importing existing EC2 instances as CML Workers."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
        aws_ec2_client: AwsEc2Client,
        settings: Settings,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self.cml_worker_repository = cml_worker_repository
        self.aws_ec2_client = aws_ec2_client
        self.settings = settings

    async def handle_async(
        self, command: ImportCMLWorkerCommand, cancellation_token: CancellationToken
    ) -> OperationResult[CMLWorkerInstanceDto]:
        """Import existing EC2 instance as CML Worker."""

        try:
            # Step 1: Discover instance in AWS
            instance = None

            if command.aws_instance_id:
                # Direct lookup by instance ID
                instance = self.aws_ec2_client.get_instance_details(
                    aws_region=AwsRegion(command.aws_region),
                    instance_id=command.aws_instance_id
                )
            else:
                # Search by AMI ID or name
                filters = {}
                if command.ami_id:
                    filters['image_ids'] = [command.ami_id]
                # Could add ami_name search here if needed

                instances = self.aws_ec2_client.list_instances(
                    region_name=AwsRegion(command.aws_region),
                    **filters
                )

                if instances and len(instances) > 0:
                    instance = instances[0]  # Take first match

            if not instance:
                return OperationResult.fail("No matching EC2 instance found")

            # Step 2: Check if already imported
            existing = await self.cml_worker_repository.get_by_aws_instance_id_async(
                instance.id
            )
            if existing:
                return OperationResult.fail(
                    f"Instance {instance.id} is already registered as worker {existing.id}"
                )

            # Step 3: Create CML Worker aggregate
            worker_name = command.name or instance.name
            worker = CMLWorker.import_from_existing_instance(
                name=worker_name,
                aws_region=command.aws_region,
                aws_instance_id=instance.id,
                instance_type=instance.type,
                ami_id=instance.image_id,
                instance_state=instance.state,
                created_by=command.created_by or "system"
            )

            # Step 4: Persist to database
            await self.cml_worker_repository.add_async(worker)

            # Step 5: Return DTO
            dto = CMLWorkerInstanceDto(
                id=worker.id,
                aws_instance_id=instance.id,
                aws_region=command.aws_region,
                instance_name=worker_name,
                ami_id=instance.image_id,
                instance_type=instance.type,
                instance_state=instance.state,
                # ... other fields
            )

            return OperationResult.ok(dto)

        except Exception as e:
            return OperationResult.fail(f"Failed to import worker: {str(e)}")
```

#### 1.2 Add Factory Method to CMLWorker Aggregate

**File:** `src/domain/entities/cml_worker.py`

```python
class CMLWorker(AggregateRoot[str, CMLWorkerState]):
    """CML Worker aggregate root."""

    # ... existing methods ...

    @staticmethod
    def import_from_existing_instance(
        name: str,
        aws_region: str,
        aws_instance_id: str,
        instance_type: str,
        ami_id: str,
        instance_state: str,
        created_by: str,
        ami_name: str | None = None,
        public_ip: str | None = None,
        private_ip: str | None = None,
    ) -> "CMLWorker":
        """Factory method to import an existing EC2 instance as a CML Worker.

        This creates a worker from an already-provisioned instance without
        creating a new EC2 instance.

        Args:
            name: Friendly name for the worker
            aws_region: AWS region where instance exists
            aws_instance_id: AWS instance ID
            instance_type: EC2 instance type (e.g., 'c5.2xlarge')
            ami_id: AMI ID used by the instance
            instance_state: Current EC2 state (running, stopped, etc.)
            created_by: User who initiated the import
            ami_name: Optional AMI name
            public_ip: Optional public IP address
            private_ip: Optional private IP address

        Returns:
            New CMLWorker aggregate with IMPORTED status
        """
        worker_id = str(uuid4())

        event = CMLWorkerImportedDomainEvent(
            aggregate_id=worker_id,
            name=name,
            aws_region=aws_region,
            aws_instance_id=aws_instance_id,
            instance_type=instance_type,
            ami_id=ami_id,
            ami_name=ami_name,
            instance_state=instance_state,
            public_ip=public_ip,
            private_ip=private_ip,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
        )

        worker = CMLWorker()
        worker.apply(event)
        return worker
```

#### 1.3 Add Domain Event

**File:** `src/domain/events/cml_worker.py`

```python
@dataclass
class CMLWorkerImportedDomainEvent(DomainEvent):
    """Event raised when an existing EC2 instance is imported as a CML Worker."""

    name: str
    aws_region: str
    aws_instance_id: str
    instance_type: str
    ami_id: str
    ami_name: str | None
    instance_state: str
    public_ip: str | None
    private_ip: str | None
    created_by: str
    created_at: datetime
```

---

### Phase 2: API Endpoint (REST Interface)

#### 2.1 Add Controller Method

**File:** `src/api/controllers/workers_controller.py`

```python
@router.post(
    "/region/{aws_region}/workers/import",
    response_model=CMLWorkerInstanceDto,
    status_code=status.HTTP_201_CREATED,
    summary="Import existing EC2 instance as CML Worker",
    description="Discover and register an existing EC2 instance without creating a new one",
)
async def import_existing_cml_worker(
    self,
    aws_region: str,
    request: ImportCMLWorkerRequest,
    user: dict = Depends(require_auth_user),
) -> CMLWorkerInstanceDto:
    """Import an existing EC2 instance as a CML Worker.

    This endpoint allows you to register EC2 instances that were created
    outside of Lablet Cloud Manager (e.g., via AWS Console, Terraform, etc.)

    You can specify either:
    - aws_instance_id: Direct lookup by instance ID
    - ami_id or ami_name: Search for instances using that AMI
    """

    command = ImportCMLWorkerCommand(
        aws_region=aws_region,
        aws_instance_id=request.aws_instance_id,
        ami_id=request.ami_id,
        ami_name=request.ami_name,
        name=request.name,
        created_by=user.get("preferred_username"),
    )

    return self.process(await self.mediator.execute_async(command))
```

#### 2.2 Add Request Model

**File:** `src/api/models/cml_worker_requests.py`

```python
class ImportCMLWorkerRequest(BaseModel):
    """Request model for importing existing EC2 instances."""

    aws_instance_id: str | None = Field(
        None,
        description="AWS EC2 instance ID (e.g., 'i-1234567890abcdef0'). "
                   "If provided, directly import this instance.",
        example="i-0abcdef1234567890"
    )

    ami_id: str | None = Field(
        None,
        description="AMI ID to search for (e.g., 'ami-0c55b159cbfafe1f0'). "
                   "Will import the first instance found with this AMI.",
        example="ami-0c55b159cbfafe1f0"
    )

    ami_name: str | None = Field(
        None,
        description="AMI name pattern to search for. "
                   "Will import the first instance found with matching AMI name.",
        example="cml-worker-ami-2.7.0"
    )

    name: str | None = Field(
        None,
        description="Friendly name for the worker (overrides instance name)",
        example="cml-worker-imported-01"
    )

    @model_validator(mode='after')
    def validate_search_criteria(self) -> 'ImportCMLWorkerRequest':
        """Ensure at least one search criterion is provided."""
        if not any([self.aws_instance_id, self.ami_id, self.ami_name]):
            raise ValueError(
                "Must provide at least one of: aws_instance_id, ami_id, or ami_name"
            )
        return self
```

---

### Phase 3: Query Enhancement (Optional)

#### 3.1 Add Query for Unregistered Instances

**File:** `src/application/queries/list_unregistered_instances_query.py`

```python
"""Query to list EC2 instances that are not yet registered as CML Workers."""

@dataclass
class ListUnregisteredInstancesQuery(Query[List[UnregisteredInstanceDto]]):
    """Query to find EC2 instances not registered in the system."""

    aws_region: str
    ami_id: str | None = None
    ami_name: str | None = None


class ListUnregisteredInstancesQueryHandler(
    QueryHandler[ListUnregisteredInstancesQuery, List[UnregisteredInstanceDto]]
):
    """Find instances in AWS that aren't tracked locally."""

    async def handle_async(
        self, query: ListUnregisteredInstancesQuery, cancellation_token
    ) -> List[UnregisteredInstanceDto]:
        """List unregistered instances."""

        # Get all instances from AWS
        aws_instances = self.aws_ec2_client.list_instances(
            region_name=AwsRegion(query.aws_region),
            image_ids=[query.ami_id] if query.ami_id else None
        )

        # Get all registered workers
        registered_workers = await self.cml_worker_repository.get_all_async()
        registered_instance_ids = {
            w.aws_instance_id for w in registered_workers if w.aws_instance_id
        }

        # Find unregistered
        unregistered = [
            UnregisteredInstanceDto(
                aws_instance_id=inst.id,
                instance_type=inst.type,
                ami_id=inst.image_id,
                state=inst.state,
                name=inst.name,
                launch_time=inst.launch_timestamp
            )
            for inst in aws_instances
            if inst.id not in registered_instance_ids
        ]

        return unregistered
```

---

## Implementation Steps (Recommended Order)

### Step 1: Domain Layer ✅

1. Add `CMLWorkerImportedDomainEvent` to `domain/events/cml_worker.py`
2. Add `import_from_existing_instance()` factory method to `CMLWorker` entity
3. Add event reducer in CMLWorker to handle the imported event

### Step 2: Application Layer ✅

1. Create `ImportCMLWorkerCommand` in `application/commands/`
2. Create `ImportCMLWorkerCommandHandler`
3. Register handler with Mediator (auto-discovered)

### Step 3: API Layer ✅

1. Create `ImportCMLWorkerRequest` model in `api/models/`
2. Add `import_existing_cml_worker()` endpoint to `WorkersController`
3. Update OpenAPI documentation

### Step 4: Testing ✅

1. Unit tests for command handler
2. Integration tests for the endpoint
3. Test with actual AWS instances

### Step 5: Documentation ✅

1. Update API docs with import endpoint
2. Add usage examples
3. Update IAM permissions doc (no new permissions needed!)

---

## API Usage Examples

### Import by Instance ID (Direct)

```bash
curl -X POST \
  'http://localhost:8030/api/workers/region/us-east-1/workers/import' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "aws_instance_id": "i-0abcdef1234567890",
    "name": "imported-worker-01"
  }'
```

### Import by AMI ID (Search)

```bash
curl -X POST \
  'http://localhost:8030/api/workers/region/us-east-1/workers/import' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "ami_id": "ami-0c55b159cbfafe1f0",
    "name": "imported-worker-02"
  }'
```

### Import by AMI Name (Pattern)

```bash
curl -X POST \
  'http://localhost:8030/api/workers/region/us-east-1/workers/import' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "ami_name": "cml-worker-ami-2.7.0",
    "name": "imported-worker-03"
  }'
```

---

## Benefits

✅ **Reuse existing infrastructure** - Import manually-created instances
✅ **Migration path** - Gradually adopt Lablet Cloud Manager
✅ **No redundant resources** - Avoid creating duplicates
✅ **Consistent management** - Manage all workers through one interface
✅ **Audit trail** - Track who imported what and when

---

## IAM Permissions

**Good news:** No additional IAM permissions required! The import functionality uses the same permissions already granted:

- ✅ `ec2:DescribeInstances` - Already required
- ✅ `ec2:DescribeTags` - Already required

---

## Risk Assessment

**Low Risk:**

- Read-only AWS operations (describe/list)
- No new EC2 instances created
- Existing instances remain unchanged
- Only creates database records

**Validations:**

- ✅ Check instance exists in AWS
- ✅ Verify not already imported (prevent duplicates)
- ✅ Validate region matches
- ✅ Audit logging for traceability

---

## Summary

**You are correct** - this feature does not exist yet. The current system can only create NEW instances, not import existing ones.

**Recommended approach:**

1. Start with Phase 1 (Command & Handler) - Core business logic
2. Add Phase 2 (API Endpoint) - User interface
3. Optionally add Phase 3 (Discovery query) - Enhanced UX

This feature would complete the worker management lifecycle and provide a smooth migration path for existing CML deployments.
