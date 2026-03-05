# LCM A2A Task Queue

This directory contains the task queue for Agent-to-Agent (A2A) communication within the Lablet Cloud Manager platform.

## Directory Structure

```
tasks/
├── README.md           # This file
├── queued/             # New tasks awaiting processing
├── in-progress/        # Tasks currently being worked on
└── completed/          # Finished tasks (retained for history)
```

## Task Lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: Task created
    queued --> in-progress: Agent claims task
    in-progress --> completed: Task finished
    in-progress --> queued: Task unclaimed (timeout)
    completed --> [*]: Archived after 7 days
```

## Task File Format

Tasks are JSON files named `task-YYYYMMDD-NNN.json`:

```json
{
    "id": "task-20250117-001",
    "title": "Brief task description",
    "description": "Detailed task description with context",
    "requester": "agent-id-requesting",
    "assignee": "agent-id-assigned",
    "priority": "low|medium|high|critical",
    "created": "2025-01-17T10:00:00Z",
    "deadline": "2025-01-18T10:00:00Z",
    "services": ["control-plane-api", "worker-controller"],
    "deliverables": [
        {
            "type": "code|document|analysis|decision",
            "description": "What needs to be delivered",
            "path": "expected/output/path"
        }
    ],
    "context": {
        "relatedDecisions": ["AD-001"],
        "relatedFiles": ["path/to/file.py"],
        "upstreamTask": "aix://task-id"
    },
    "status": "queued",
    "statusHistory": [
        {
            "status": "queued",
            "timestamp": "2025-01-17T10:00:00Z",
            "agent": "lcm-principal-architect"
        }
    ],
    "result": null
}
```

## Priority Levels

| Priority | Response Time | Use Case |
|----------|---------------|----------|
| `critical` | < 1 hour | Production issues, security vulnerabilities |
| `high` | < 4 hours | Breaking changes, blocked work |
| `medium` | < 24 hours | Feature implementation, documentation |
| `low` | < 1 week | Refactoring, optimization, nice-to-have |

## Cross-Service Tasks

For tasks affecting multiple microservices, include all affected services in the `services` array. The assigned agent is responsible for coordinating across services.

## Upstream Tasks

Tasks originating from the AIX Architecture Team include an `upstreamTask` reference. Results should be reported back to the upstream task queue.

## Task Result Format

When completing a task, update the `result` field:

```json
{
    "result": {
        "status": "success|partial|failed",
        "summary": "Brief description of outcome",
        "deliverables": [
            {
                "type": "code",
                "path": "path/to/implementation.py",
                "description": "Implemented feature X"
            }
        ],
        "decisions": ["AD-002"],
        "insights": ["Pattern discovered: ..."],
        "followUp": ["task-20250118-001"]
    }
}
```
