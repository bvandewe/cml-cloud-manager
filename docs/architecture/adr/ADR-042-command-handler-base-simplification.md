# ADR-042: CommandHandlerBase Dependency Simplification

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-01 |
| **Deciders** | Platform Team |
| **Related ADRs** | [ADR-003](./ADR-003-cloudevents-for-integration.md) (CloudEvents Integration), [ADR-010](./ADR-010-service-unification-neuroglia.md) (Service Unification) |
| **Knowledge Refs** | AD-OTEL-CQRS-001 |

## Context

### Current Inheritance Hierarchy

The control-plane-api uses a base class `CommandHandlerBase` for all CQRS command handlers:

```
CommandHandler (Neuroglia framework)
    └── CommandHandlerBase (application layer)
            ├── __init_subclass__ → OTEL span enrichment
            ├── mediator: Mediator
            ├── mapper: Mapper
            ├── cloud_event_bus: CloudEventBus
            ├── cloud_event_publishing_options: CloudEventPublishingOptions
            └── publish_cloud_event_async()
                    └── 73 concrete command handlers inherit this
```

For queries, a lean base exists:

```
QueryHandler (Neuroglia framework)
    └── QueryHandlerBase (application layer)
            └── __init_subclass__ → OTEL span enrichment (only concern)
                    └── 29 concrete query handlers inherit this
```

### Problem Statement

Empirical analysis of the 73 handlers inheriting `CommandHandlerBase` reveals:

| Dependency | Handlers declaring it | Handlers actually using it | Usage rate |
|-----------|:--------------------:|:--------------------------:|:----------:|
| `cloud_event_bus` | 73 | **1** (`UpdatePipelineProgressCommandHandler`) | 1.4% |
| `cloud_event_publishing_options` | 73 | **1** (same) | 1.4% |
| `mapper` | 73 | **0** | 0% |
| `mediator` | 73 | **4** (session orchestration handlers) | 5.5% |

Additionally, **16 command handlers** don't inherit `CommandHandlerBase` at all because they
only need a repository — but they still need OTEL enrichment, currently applied via a
`@instrumented` decorator (a second, inconsistent pattern).

### Violations Identified

1. **Interface Segregation Principle (ISP)**: 72/73 handlers depend on `CloudEventBus` they never use. All 73 carry a `Mapper` none of them invoke.

2. **Single Responsibility Principle (SRP)**: `CommandHandlerBase` conflates three concerns:
   - Cross-cutting observability (OTEL span enrichment)
   - Integration infrastructure (CloudEvent publishing)
   - Service composition (Mediator, Mapper injection)

3. **Clean Architecture boundary blur**: `CloudEventBus` is an integration-layer concern
   injected at the application-layer base class, violating the dependency rule.

4. **Dual instrumentation pattern**: Commands use either `CommandHandlerBase` (inheritance)
   or `@instrumented` (decorator) for the same OTEL concern — inconsistent and forgettable.

5. **Test overhead**: Every handler unit test mocks 4 unused dependencies in `super().__init__()`.

## Decision

**Simplify `CommandHandlerBase` to a zero-dependency observability shell (symmetric with `QueryHandlerBase`). Move CloudEvent publishing to a dedicated integration-layer service injected only by the handler that needs it.**

### Target Inheritance Hierarchy

```
CommandHandler (Neuroglia framework)
    └── CommandHandlerBase (application layer)
            └── __init_subclass__ → OTEL span enrichment (ONLY concern)
                    └── All concrete command handlers inherit this
                         (each declares only the deps it actually uses)

CloudEventPublisher (integration layer — NEW)
    └── publish_cloud_event_async()
    └── Injected only by UpdatePipelineProgressCommandHandler
```

For comparison, the query side remains unchanged (already at target state):

```
QueryHandler (Neuroglia framework)
    └── QueryHandlerBase (application layer)
            └── __init_subclass__ → OTEL span enrichment (ONLY concern)
```

### Dependency Injection After Refactoring

```python
# CommandHandlerBase — zero dependencies, pure observability hook
class CommandHandlerBase(CommandHandler):
    """Base class providing automatic OTEL span enrichment for command handlers."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        wrap_handle_async_with_enrichment(cls)


# Typical handler — injects ONLY what it uses
class CreateLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateLabletSessionCommand, OperationResult[...]],
):
    def __init__(self, session_repository: LabletSessionRepository):
        self.session_repository = session_repository


# Orchestration handler — injects mediator because it dispatches sub-commands
class TerminateLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[TerminateLabletSessionCommand, OperationResult[...]],
):
    def __init__(self, mediator: Mediator, session_repository: ...):
        self.mediator = mediator
        self.session_repository = session_repository


# The ONE handler that publishes cloud events — injects the publisher
class UpdatePipelineProgressCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdatePipelineProgressCommand, OperationResult[...]],
):
    def __init__(self, cloud_event_publisher: CloudEventPublisher, ...):
        self.cloud_event_publisher = cloud_event_publisher
```

### CloudEventPublisher Service (New)

```python
# integration/services/cloud_event_publisher.py
class CloudEventPublisher:
    """Publishes integration events as CloudEvents to the event bus.

    Extracted from CommandHandlerBase to adhere to ISP. Only handlers
    that actually emit integration events should inject this service.
    """

    def __init__(
        self,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
    ):
        self.cloud_event_bus = cloud_event_bus
        self.cloud_event_publishing_options = cloud_event_publishing_options

    async def publish_async(self, event: IntegrationEvent) -> None:
        """Convert IntegrationEvent to CloudEvent and publish."""
        ...  # Logic moved verbatim from CommandHandlerBase.publish_cloud_event_async
```

## Rationale

1. **ISP compliance**: Each handler declares exactly the dependencies it consumes. Constructor
   signatures become truthful contracts.

2. **Symmetric with queries**: `CommandHandlerBase` and `QueryHandlerBase` become structurally
   identical — both are zero-dependency observability shells.

3. **Eliminates dual pattern**: The `@instrumented` decorator becomes unnecessary. All handlers
   (including the 16 that previously couldn't use `CommandHandlerBase`) now inherit it naturally
   since it no longer forces unwanted dependencies.

4. **Clean Architecture enforcement**: CloudEvent publishing moves to the integration layer
   where it belongs, injected only at the composition root (DI registration) and only into
   the handler that needs it.

5. **Reduced test complexity**: Handler tests no longer mock 4 services they never exercise.
   Typical test setup shrinks from 6+ mocks to 1–2.

6. **Future safety**: When new handlers are added, they inherit `CommandHandlerBase` for
   observability (single pattern, no decorator to forget) and inject only domain-relevant deps.

## Consequences

### Positive

- All CQRS handlers (commands + queries) follow a single, consistent observability pattern
- `@instrumented` decorator can be deprecated (kept only for edge cases)
- Constructor signatures accurately document each handler's actual dependencies
- Test setup is minimal — mocks match real usage
- New handlers are impossible to create without OTEL enrichment (structural enforcement)

### Negative / Migration Cost

- **73 handler files** need `__init__` signature cleanup (remove unused params + `super()` call)
- **1 handler** (`UpdatePipelineProgressCommandHandler`) needs refactoring to inject `CloudEventPublisher`
- **73 test files** need mock cleanup (remove unused mock params) — but tests become simpler
- **DI registration** in `main.py` needs `CloudEventPublisher` registered as a service

### Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Regression during 73-file migration | Mechanical transformation; verified by existing 1190-test suite |
| Future handlers needing cloud events don't know about `CloudEventPublisher` | Documented in copilot-instructions.md; only 1 handler ever needed it in 10 months |
| `Mapper` removal breaks future use | `Mapper` has 0 usages across all 73 handlers; can be re-added if needed |
| Neuroglia DI resolution changes | `CommandHandlerBase` without `__init__` uses Python default; Neuroglia resolves concrete class constructors independently |

## Implementation Plan

### Phase 1: Extract `CloudEventPublisher` (isolated, no breaking changes)

1. Create `integration/services/cloud_event_publisher.py`
   - Move `publish_cloud_event_async()` logic verbatim from `CommandHandlerBase`
   - Register as singleton in `main.py` DI container

2. Update `UpdatePipelineProgressCommandHandler`
   - Inject `CloudEventPublisher` directly
   - Replace `self.publish_cloud_event_async(...)` → `self.cloud_event_publisher.publish_async(...)`
   - Verify via test for that specific handler

3. Validate: all 1190+ tests pass, cloud event emission still works

### Phase 2: Slim down `CommandHandlerBase`

4. Remove from `CommandHandlerBase`:
   - `__init__()` method entirely (or reduce to `pass`)
   - `mediator`, `mapper`, `cloud_event_bus`, `cloud_event_publishing_options` attributes
   - `publish_cloud_event_async()` method
   - Imports for CloudEvent/Mapper/Mediator

5. Result: `CommandHandlerBase` becomes:

   ```python
   from neuroglia.mediation import CommandHandler
   from infrastructure.observability.cqrs_instrumentation import wrap_handle_async_with_enrichment

   class CommandHandlerBase(CommandHandler):
       """Base class providing automatic OTEL span enrichment for all command handlers."""

       def __init_subclass__(cls, **kwargs):
           super().__init_subclass__(**kwargs)
           wrap_handle_async_with_enrichment(cls)
   ```

### Phase 3: Migrate 73 handlers (mechanical)

6. For each handler inheriting `CommandHandlerBase`:
   - Remove `cloud_event_bus`, `cloud_event_publishing_options`, `mapper` from `__init__` params
   - Remove `super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)`
   - Keep `mediator` param **only** if handler uses `self.mediator` (4 handlers)
   - Remove unused imports (`CloudEventBus`, `CloudEventPublishingOptions`, `Mapper`)

7. For the 16 handlers currently using `@instrumented`:
   - Replace `@instrumented` + `CommandHandler[...]` with `CommandHandlerBase, CommandHandler[...]`
   - Remove `from infrastructure.observability.cqrs_instrumentation import instrumented`

### Phase 4: Cleanup

8. Remove `@instrumented` decorator from `cqrs_instrumentation.py` (or mark as deprecated utility)
9. Update `copilot-instructions.md` to reflect new pattern
10. Run full test suite, lint, format
11. Update unit tests: remove unnecessary mocks for `mapper`, `cloud_event_bus`, etc.

### Verification Criteria

- All tests pass (1190+)
- OTEL enrichment scan shows 100% coverage (enriched == total handlers)
- `grep -rn "cloud_event_bus" application/commands/` returns only `UpdatePipelineProgressCommandHandler`
- `grep -rn "@instrumented" application/commands/` returns 0 results
- `ruff check` clean (no new violations)

## Alternatives Considered

### A. Force all handlers onto `CommandHandlerBase` (with cloud event deps)

Rejected: ISP violation; 98.6% of handlers carry unused dependencies.

### B. Make cloud event params optional (`= None`)

Rejected: Breaks type safety; runtime null-checks for `publish_cloud_event_async`;
doesn't fix the Mapper (0% usage) problem.

### C. Mixin for cloud events

Rejected: Multiple inheritance complexity with Neuroglia's generic `CommandHandler[T, R]`;
DI container may not resolve mixin dependencies cleanly.

### D. Service Locator (inject via `service_provider`)

Rejected: Hides dependencies (anti-pattern); harder to test; loses constructor explicitness.
