---
tags:
  - lablet
  - lifecycle
  - development
  - operations
  - pipeline
  - overview
  - documentation
---

# Lablet Lifecycle Overview

This document provides a comprehensive overview of the complete Lablet lifecycle, encompassing both **Development** and **Operations** pipelines. Each pipeline has its own distinct state machine, stakeholders, and processes that work together to deliver high-quality learning experiences.

## DEV vs OPS Two-Pipeline Lifecycle

The CML Lablets platform employs a **dual-pipeline architecture** that separates content development concerns from operational delivery concerns:

```mermaid
---
title: High-Level Two-Pipeline Lifecycle
---
flowchart LR
    subgraph DEV ["🔧 Development Pipeline"]
        D1["📝 Concept"] --> D2["🎨 Design"] --> D3["🏗️ Build"] --> D4["🧪 Test"] --> D5["✅ Production"]
    end

    subgraph OPS ["⚙️ Operations Pipeline"]
        O1["📅 Scheduled"] --> O2["🔄 Provisioned"] --> O3["👤 Active"] --> O4["📊 Complete"]
    end

    D5 -.->|"Lablet Definition"| O1

    classDef devNode fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,color:#000
    classDef opsNode fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000

    class D1,D2,D3,D4,D5 devNode
    class O1,O2,O3,O4 opsNode
```

### 1. Development Pipeline (Lablet Definition)

- **Focus**: Creating and refining lablet content and specifications (in Mosaic)
- **Primary Stakeholder**: Exam Project Managers (EPMs) and Subject Matter Experts (SMEs)
- **Lifecycle**: Iterative content development with quality gates
- **Output**: Validated Lablet Definitions ready for deployment

### 2. Operations Pipeline (Lablet Instance)

- **Focus**: Delivering live lablet sessions to candidates
- **Primary Stakeholder**: Platform Operations Teams
- **Lifecycle**: Linear instance provisioning with automated state transitions
- **Output**: Scored lab results and candidate feedback

## Development Pipeline: Lablet Definition Lifecycle

```mermaid
---
title: Development Pipeline - Lablet Definition States
---
stateDiagram-v2
    [*] --> concept : EPM initiates content

    concept --> design : Requirements approved
    note right of concept
        • Initial concept validation
        • Resource estimation
        • Stakeholder approval
    end note

    design --> build : Architecture finalized
    note right of design
        • CML topology design
        • Content framework
        • Assessment criteria
    end note

    build --> test : Content created
    note left of build
        • CML topology implementation
        • Mosaic content creation
        • Verification scripts
    end note

    test --> review : Testing complete
    note left of test
        • Functional testing
        • Performance validation
        • Content review
    end note

    review --> deploy : Quality approved
    note right of review
        • Technical review
        • Content standards check
        • Stakeholder sign-off
    end note

    deploy --> production : Deployment verified
    note left of deploy
        • Staging deployment
        • Integration testing
        • Production readiness
    end note

    production --> maintain : In production
    note right of production
        • Live operational state
        • Performance monitoring
        • Continuous improvement
    end note

    maintain --> retire : End of lifecycle
    note left of maintain
        • Regular updates
        • Bug fixes
        • Enhancement requests
    end note

    retire --> [*]
    note left of retire
        • Graceful retirement
        • Data archival
        • Documentation update
    end note

    %% Revision loops
    test --> build : Issues found
    review --> build : Major revisions needed
    deploy --> build : Deployment issues
    maintain --> build : Updates required

    classDef devState fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    classDef activeState fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef prodState fill:#e8f5e8,stroke:#388e3c,stroke-width:2px

    class concept,design devState
    class build,test,review,deploy activeState
    class production,maintain,retire prodState
```

### Development Pipeline Phases

| Phase          | Duration  | Key Activities                               | Stakeholders                       | Success Criteria                |
| -------------- | --------- | -------------------------------------------- | ---------------------------------- | ------------------------------- |
| **Concept**    | 1-2 weeks | Requirements gathering, feasibility analysis | EPM, Subject Matter Experts        | Approved concept document       |
| **Design**     | 2-3 weeks | Architecture design, content planning        | EPM, Technical Teams               | Finalized design specifications |
| **Build**      | 4-8 weeks | Content creation, topology implementation    | EPM, Content Developers            | Functional prototype            |
| **Test**       | 2-3 weeks | Validation testing, performance benchmarking | EPM, QA Teams                      | Test results meeting criteria   |
| **Review**     | 1-2 weeks | Quality assurance, stakeholder approval      | Management, Technical Review Board | Quality approval obtained       |
| **Deploy**     | 1 week    | Staging deployment, integration testing      | DevOps, Platform Teams             | Successful staging deployment   |
| **Production** | Ongoing   | Live operations, monitoring                  | Operations Teams                   | Stable production operation     |
| **Maintain**   | Ongoing   | Updates, enhancements, support               | EPM, Technical Teams               | Continuous improvement metrics  |

## Operations Pipeline: Lablet Instance Lifecycle

```mermaid
---
title: Operations Pipeline - Lablet Instance States (11-State System)
---
stateDiagram-v2
    [*] --> scheduled : PVUE Driver<br/>(ALII S1 call)

    scheduled --> pending : Lab Schedule Manager<br/>(calendar trigger)
    note right of scheduled
        Exam session scheduled
        Resources reserved
    end note

    pending --> initializing : LabRuntimeAgent<br/>(provision request)
    note right of pending
        Waiting for CML Worker
        capacity allocation
    end note

    initializing --> ready_for_user : LabOrchestrator<br/>(topology ready)
    note left of initializing
        • CML topology creation
        • Device configuration
        • Network setup
        • Pre-init hooks
    end note

    ready_for_user --> running : PVUE Driver<br/>(ALII S2 call)
    note right of ready_for_user
        Lab URL available
        Candidate can access
    end note

    running --> ready_for_grading : PVUE Driver<br/>(ALII S3 call)
    note left of running
        Candidate performing
        lab exercises
    end note

    ready_for_grading --> grading : GradingEngine<br/>(auto-trigger)
    note right of ready_for_grading
        Candidate submitted work
        State captured for grading
    end note

    grading --> graded : GradingEngine<br/>(evaluation complete)
    note left of grading
        • Output collection
        • Automated scoring
        • Rubric evaluation
    end note

    graded --> reviewed : EPM/Manager<br/>(if required)
    note right of graded
        ScoreReport generated
        May require manual review
    end note

    reviewed --> submitted : LabControlPlaneAPI<br/>(admin approval)
    note left of reviewed
        Final score validation
        Quality assurance check
    end note

    submitted --> terminated : LabRuntimeAgent<br/>(cleanup trigger)
    note right of submitted
        Score sent to PVUE
        Session complete
    end note

    terminated --> [*]
    note left of terminated
        • Resources cleaned up
        • Post-terminate hooks
        • Audit logging complete
    end note

    %% Direct transitions for special cases
    graded --> submitted : Auto-submit<br/>(no review needed)

    %% Error recovery paths
    initializing --> terminated : Initialization failure
    running --> terminated : System error
    grading --> terminated : Grading failure

    classDef scheduleState fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef activeState fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    classDef gradingState fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    classDef endState fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px

    class scheduled,pending scheduleState
    class initializing,ready_for_user,running activeState
    class ready_for_grading,grading,graded,reviewed gradingState
    class submitted,terminated endState
```

### Operations Pipeline States

| State                 | Average Duration | Key Activities                               | Responsible System   | Success Criteria                  |
| --------------------- | ---------------- | -------------------------------------------- | -------------------- | --------------------------------- |
| **scheduled**         | Variable         | PVUE scheduling, resource reservation        | PVUE Driver          | Session scheduled successfully    |
| **pending**           | < 5 minutes      | Resource allocation, CML worker assignment   | Lab Schedule Manager | Resources allocated               |
| **initializing**      | 3-7 minutes      | VM boot, network setup, topology deployment  | LabRuntimeAgent      | All nodes running, topology ready |
| **ready-for-user**    | < 30 seconds     | Health checks, candidate handoff preparation | LabOrchestrator      | Access URL validated              |
| **running**           | 120-180 minutes  | User activities, monitoring, logging         | Active Session       | Candidate actively using lab      |
| **ready-for-grading** | < 1 minute       | State capture, artifact collection           | PVUE Driver          | All required artifacts collected  |
| **grading**           | 2-5 minutes      | Script execution, rubric evaluation          | GradingEngine        | Score calculated successfully     |
| **graded**            | Instant          | Score calculation, feedback generation       | GradingEngine        | Score report generated            |
| **reviewed**          | Variable         | Human review, score adjustment (if needed)   | EPM/SME              | Final score validated             |
| **submitted**         | < 30 seconds     | Result transmission, audit logging           | LabControlPlaneAPI   | Score transmitted to PVUE         |
| **terminated**        | 1-2 minutes      | Resource cleanup, final logging              | LabRuntimeAgent      | All resources released            |

## Pipeline Integration Points

### Development → Operations Handoff

The transition from Development Pipeline to Operations Pipeline occurs when a Lablet Definition moves to **production** state and becomes available for operational deployment:

```mermaid
flowchart LR
    subgraph "Development Pipeline"
        DEV_PROD[Production<br/>State]
    end

    subgraph "Operations Pipeline"
        OPS_SCHED[Scheduled<br/>State]
    end

    DEV_PROD -->|Lablet Definition<br/>Available| OPS_SCHED

    subgraph "Handoff Artifacts"
        ARTIFACTS[• CML Topology Files<br/>• Mosaic Content<br/>• Grading Scripts<br/>• Configuration Data<br/>• Performance Baselines]
    end

    DEV_PROD --> ARTIFACTS
    ARTIFACTS --> OPS_SCHED
```

### Feedback Loop: Operations → Development

Operational insights feed back into the development pipeline to drive continuous improvement:

```mermaid
flowchart RL
    subgraph "Operations Data"
        METRICS[• Performance Metrics<br/>• Error Patterns<br/>• User Feedback<br/>• Resource Utilization]
    end

    subgraph "Development Improvements"
        IMPROVE[• Content Updates<br/>• Performance Optimization<br/>• Bug Fixes<br/>• Feature Enhancements]
    end

    METRICS -->|Continuous<br/>Feedback| IMPROVE
```

## Key Stakeholders & Responsibilities

### Development Pipeline Stakeholders

- **Exam Project Managers (EPMs)**: Content creation, validation, lifecycle management
- **Subject Matter Experts (SMEs)**: Technical content review and validation
- **Content Developers**: Implementation of lablet content and topologies
- **Technical Teams**: Architecture, infrastructure, and integration support
- **Quality Assurance**: Testing, validation, and compliance verification

### Operations Pipeline Stakeholders

- **Platform Operations**: Infrastructure management and monitoring
- **Lab Runtime Systems**: Automated provisioning and state management
- **Grading Systems**: Automated scoring and evaluation
- **Support Teams**: Issue resolution and customer support
- **PVUE Integration**: External system integration and data exchange

## Success Metrics Across Pipelines

### Development Pipeline KPIs

- **Development Velocity**: Average time from concept to production
- **Quality Score**: Percentage of lablets meeting quality standards on first review
- **Resource Efficiency**: Actual vs. estimated development resources
- **Stakeholder Satisfaction**: EPM and SME satisfaction scores

### Operations Pipeline KPIs

- **Availability**: Percentage uptime for operational lablet instances
- **Performance**: Average initialization and grading times
- **Success Rate**: Percentage of sessions completing successfully
- **User Experience**: Candidate satisfaction and completion rates

## AI & Cloud-Native Enhancements (Phase 4)

Both pipelines benefit from AI and cloud-native capabilities introduced in Phase 4:

### Development Pipeline AI Enhancements

- **Intelligent Content Validation**: AI-powered content quality analysis
- **Automated Testing**: AI-driven test case generation and execution
- **Performance Prediction**: ML models predicting resource requirements
- **Content Optimization**: AI recommendations for content improvements

### Operations Pipeline AI Enhancements

- **Predictive Scaling**: AI-based resource allocation and scaling
- **Intelligent Monitoring**: ML-powered anomaly detection and alerting
- **Automated Troubleshooting**: AI-assisted issue diagnosis and resolution
- **Personalized Experiences**: AI-driven user experience optimization

### Cloud-Native Integration

- **Hybrid Cloud Connectivity**: Integration with Webex, Intersight, and Meraki
- **Multi-Cloud Operations**: Seamless operation across cloud providers
- **Service Mesh Architecture**: Enhanced connectivity and observability
- **Cloud-Native Scaling**: Dynamic resource scaling based on demand

---

**Related Documentation:**

- [Development Pipeline Details](dev/) - Comprehensive development process documentation
- [Operations Pipeline Details](ops/) - Complete operational procedures and state management
- [Master Content Checklist](../project/master-content-checklist.md) - EPM operational checklist
- [Architecture Overview](../architecture.md) - Platform architecture and design principles
