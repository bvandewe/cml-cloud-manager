# Multi-Repository Workspace Structure for AI Agent Systems

## Context

This document proposes a unified workspace structure for the Mozart microservices ecosystem that supports:

1. **VS Code Copilot Agents** (`.github/agents/`)
2. **Google Antigravity / Jules** (`.agent/rules/`, `.agent/workflows/`, `.agent/teams/`)
3. **A2A Protocol** (Agent-to-Agent communication)
4. **Knowledge Sharing** across repositories

## Proposed Directory Structure

```
Mozart/
├── .agent/                                  # 🌐 GLOBAL Agent Configuration (Antigravity)
│   ├── rules/                               # Cross-repo behavioral rules
│   │   ├── global-standards.md              # Coding standards, commit conventions
│   │   ├── domain-glossary.md               # Shared domain terminology
│   │   └── security-protocols.md            # Auth, secrets, compliance
│   ├── workflows/                           # Cross-repo workflows
│   │   ├── release-process.md               # Multi-service release coordination
│   │   ├── integration-testing.md           # Cross-service test orchestration
│   │   └── incident-response.md             # On-call escalation
│   ├── teams/                               # Global team definitions
│   │   ├── platform-team.team.md            # Infrastructure & shared services
│   │   ├── domain-team.team.md              # Business domain experts
│   │   └── security-team.team.md            # Security & compliance
│   └── a2a/                                 # 🤖 Agent-to-Agent Protocol
│       ├── registry.json                    # Agent Card registry
│       ├── tasks/                           # Pending inter-agent tasks
│       │   ├── queued/                      # Tasks waiting for assignment
│       │   ├── in-progress/                 # Tasks being worked on
│       │   └── completed/                   # Archived completed tasks
│       └── channels/                        # Communication channels
│           ├── architecture.channel.md      # Architecture decisions broadcast
│           └── incidents.channel.md         # Incident coordination
│
├── .github/                                 # 🟣 VS Code Copilot Agents
│   ├── agents/                              # Global agent definitions
│   │   ├── mozart-orchestrator.agent.md     # Cross-repo coordination
│   │   └── security-auditor.agent.md        # Security scanning
│   └── copilot-instructions.md              # Global Copilot context
│
├── src/microservices/
│   │
│   ├── aix/                                 # 🤖 AIX - Agentic Infrastructure
│   │   ├── .agent/
│   │   │   ├── rules/
│   │   │   │   ├── principal-architect.md
│   │   │   │   ├── doc-architect.md
│   │   │   │   ├── frontend-architect.md
│   │   │   │   └── project-overview.md
│   │   │   ├── workflows/
│   │   │   │   ├── implement-new-feature.md
│   │   │   │   ├── add-new-entity.md
│   │   │   │   ├── implement-ui.md
│   │   │   │   └── testing.md
│   │   │   ├── teams/
│   │   │   │   └── architecture-core.team.md
│   │   │   └── a2a/
│   │   │       └── card.json                 # AIX Agent Card
│   │   ├── .github/
│   │   │   ├── agents/
│   │   │   │   ├── aix-principal-architect.agent.md
│   │   │   │   ├── aix-senior-architect.agent.md
│   │   │   │   ├── aix-document-master.agent.md
│   │   │   │   └── aix-code-extractor.agent.md
│   │   │   └── copilot-instructions.md
│   │   └── src/
│   │       ├── tools-provider/              # MCP Tool Provider
│   │       ├── agent-host/                  # Chat UI + Agent Runtime
│   │       ├── knowledge-manager/           # Knowledge Graph + Semantic Search
│   │       └── skills-manager/              # Skill Templates
│   │
│   ├── lablet-cloud-manager/                # 🔬 LCM - Lab Cloud Management
│   │   ├── .agent/
│   │   │   ├── rules/
│   │   │   │   ├── lcm-architect.md
│   │   │   │   └── cml-domain-expert.md
│   │   │   ├── workflows/
│   │   │   │   ├── worker-lifecycle.md
│   │   │   │   └── lab-provisioning.md
│   │   │   └── a2a/
│   │   │       └── card.json                 # LCM Agent Card
│   │   ├── .github/
│   │   │   ├── agents/
│   │   │   │   └── lcm-senior-architect.agent.md
│   │   │   └── copilot-instructions.md
│   │   └── src/
│   │       ├── control-plane-api/
│   │       ├── resource-scheduler/
│   │       ├── lablet-controller/
│   │       ├── worker-controller/
│   │       └── core/
│   │
│   └── [future-domains]/                    # 📦 Domain Apps
│       ├── track-manager/
│       ├── grading-engine/
│       ├── schedule-manager/
│       └── pod-manager/
│
└── infrastructure/                          # 🏗️ Shared Infrastructure
    ├── docker-compose.infra.yml             # Shared services (Keycloak, MongoDB, Redis)
    ├── helm/                                # Kubernetes charts
    └── terraform/                           # Cloud provisioning
```

## Agent-to-Agent (A2A) Protocol

### Agent Card Schema (`a2a/card.json`)

```json
{
  "$schema": "https://a2a.dev/schema/agent-card.json",
  "name": "aix-principal-architect",
  "version": "1.0.0",
  "description": "Principal Architect & Strategic Liaison for AIX",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "skills": [
    {
      "id": "strategic-analysis",
      "name": "Strategic Analysis",
      "description": "Analyze code/strategy and translate between executive and technical contexts"
    },
    {
      "id": "documentation-governance",
      "name": "Documentation Governance",
      "description": "Maintain aix-executive namespace and delegate doc updates"
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text", "artifact"],
  "endpoint": {
    "url": "mcp://aix-agent-host:8050/agents/principal-architect",
    "protocol": "mcp"
  },
  "authentication": {
    "schemes": ["oauth2"],
    "oauth2": {
      "tokenUrl": "http://localhost:8041/realms/aix/protocol/openid-connect/token",
      "scopes": ["agent:invoke"]
    }
  }
}
```

### Task Schema (`a2a/tasks/queued/task-001.json`)

```json
{
  "id": "task-001",
  "type": "change-request",
  "priority": "high",
  "source": {
    "agent": "aix-principal-architect",
    "repository": "aix"
  },
  "target": {
    "agent": "aix-document-master",
    "repository": "aix"
  },
  "subject": "Update API documentation for new skill import endpoint",
  "description": "The skills-manager now supports OAuth2 client_credentials flow. Update /docs/api/skills-manager.md with the new authentication section.",
  "context": {
    "files": [
      "src/skills-manager/api/controllers/skills_controller.py",
      "src/agent-host/integration/services/skills_manager_client.py"
    ],
    "relatedDecisions": ["AD-EXEC-042"]
  },
  "status": "queued",
  "createdAt": "2026-01-17T10:00:00Z"
}
```

## Repository Categories

### 1. Framework Layer (`neuroglia-*`)

Core framework providing:

- DDD/CQRS/ES patterns
- Clean Architecture structure
- Agentic primitives

```
neuroglia-framework/
├── .agent/
│   ├── rules/
│   │   └── framework-patterns.md           # CQRS, Event Sourcing rules
│   └── a2a/
│       └── card.json                        # Framework support agent
├── core/                                    # Core abstractions
├── agentic/                                 # Agent runtime
├── web/                                     # Web application patterns
└── samples/                                 # Reference implementations
```

### 2. Infrastructure Layer (`mozart-infra`)

Shared infrastructure services:

| Service | Purpose | Port |
|---------|---------|------|
| Keycloak | Identity Provider (OAuth2/OIDC) | 8041 |
| MongoDB | Document Store | 27017 |
| Redis | Cache/Sessions | 6379 |
| EventStore | Event Sourcing | 2113 |
| Neo4j | Knowledge Graph | 7474 |
| Qdrant | Vector Search | 6333 |
| MinIO | Object Storage | 9000 |
| OTEL Collector | Observability | 4317 |

### 3. Domain Apps Layer

Business domain microservices:

| App | Purpose | Dependencies |
|-----|---------|--------------|
| skills-manager | Skill template management | MongoDB, Keycloak |
| track-manager | Certification track orchestration | MongoDB, Keycloak |
| grading-engine | Assessment scoring | MongoDB, skills-manager |
| schedule-manager | Lab scheduling | MongoDB, etcd |
| pod-manager | Pod lifecycle management | MongoDB, K8s API |

### 4. Agentic Teams Layer

Agent team definitions that span repositories:

```yaml
# .agent/teams/architecture-core.team.md

Members:
  - aix-principal-architect (aix repo)
  - aix-document-master (aix repo)
  - aix-senior-architect (aix repo)
  - lcm-senior-architect (lcm repo)

Communication:
  - Channel: architecture.channel.md
  - Protocol: A2A Tasks

Knowledge Namespaces:
  - aix-executive (owned by principal-architect)
  - aix-architecture (shared read)
  - lcm-architecture (owned by lcm-senior-architect)
```

## VS Code Multi-Root Workspace Configuration

```jsonc
// mozart.code-workspace
{
  "folders": [
    {
      "name": "🌐 Mozart Root",
      "path": "."
    },
    {
      "name": "🤖 aix",
      "path": "src/microservices/aix"
    },
    {
      "name": "🔬 lablet-cloud-manager",
      "path": "src/microservices/lablet-cloud-manager"
    },
    {
      "name": "📦 neuroglia-framework",
      "path": "../neuroglia-framework"  // Separate repo
    }
  ],
  "settings": {
    "github.copilot.chat.agentInstructions": {
      "global": ".github/copilot-instructions.md",
      "folders": {
        "aix": "src/microservices/aix/.github/copilot-instructions.md",
        "lablet-cloud-manager": "src/microservices/lablet-cloud-manager/.github/copilot-instructions.md"
      }
    }
  }
}
```

## Agent Discovery Protocol

### 1. Local Discovery (Same Repo)

```yaml
# In agent prompt
Look for peer agents in:
- .agent/teams/*.team.md
- .github/agents/*.agent.md
```

### 2. Cross-Repo Discovery (A2A)

```yaml
# Query the global registry
Read: ../../.agent/a2a/registry.json
Filter: agents with matching skills
Invoke: via MCP endpoint in agent card
```

### 3. Registry Format

```json
// Mozart/.agent/a2a/registry.json
{
  "version": "1.0",
  "agents": [
    {
      "id": "aix-principal-architect",
      "repository": "aix",
      "cardPath": "src/microservices/aix/.agent/a2a/card.json",
      "skills": ["strategic-analysis", "documentation-governance"],
      "status": "active"
    },
    {
      "id": "lcm-senior-architect",
      "repository": "lablet-cloud-manager",
      "cardPath": "src/microservices/lablet-cloud-manager/.agent/a2a/card.json",
      "skills": ["aws-infrastructure", "cml-domain-expert"],
      "status": "active"
    }
  ]
}
```

## Implementation Priorities

### Phase 1: Foundation

1. ✅ Establish `.agent/` structure in AIX (done)
2. ⬜ Create `docker-compose.infra.yml` for shared infrastructure
3. ⬜ Define A2A card schema for existing agents

### Phase 2: Cross-Repo

4. ⬜ Create global `.agent/` at Mozart root
2. ⬜ Establish agent registry
3. ⬜ Implement task queue for change requests

### Phase 3: Communication

7. ⬜ Define channel message formats
2. ⬜ Implement MCP-based agent invocation
3. ⬜ Build agent discovery service

## Open Questions

1. **Task Persistence**: Should A2A tasks be stored in Git or in a database (MongoDB/Redis)?
2. **Real-time Communication**: Use SSE/WebSocket channels or poll-based task queues?
3. **Agent Authentication**: Per-agent OAuth2 clients or shared service account?
4. **Knowledge Sync**: How to sync knowledge namespaces across repos?
