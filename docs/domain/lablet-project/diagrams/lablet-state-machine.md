# Lablet Instance State Machine

This diagram shows the lifecycle states of a Lablet Instance from creation to termination, including the stakeholders and systems that trigger state transitions.

## Current State Implementation

```mermaid
---
title: Lablet Instance Lifecycle - 11 States
---
stateDiagram-v2
    [*] --> scheduled : PVUE Driver<br/>(ALII S1 call)

    scheduled --> pending : Lab Schedule Manager<br/>(calendar trigger)

    pending --> initializing : LabRuntimeAgent<br/>(provision request)
    note right of pending
        Waiting for available
        CML Worker capacity
    end note

    initializing --> ready_for_user : LabOrchestrator<br/>(topology ready)
    note right of initializing
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

    running --> ready_for_grading : PVUE Driver<br/>(ALII S3 call - Next Item)
    note left of running
        Candidate performing
        lab tasks and exercises
    end note

    ready_for_grading --> grading : GradingEngine<br/>(auto-trigger)
    note right of ready_for_grading
        Candidate clicked
        "Next Item" in PVUE
    end note

    grading --> graded : GradingEngine<br/>(evaluation complete)
    note left of grading
        • Device output collection
        • Automated scoring
        • Rubric evaluation
    end note

    graded --> reviewed : EPM/Manager<br/>(quality assurance)
    note right of graded
        ScoreReport generated
        Ready for review
    end note

    reviewed --> submitted : LabControlPlaneAPI<br/>(admin approval)
    note left of reviewed
        Final score validation
        and approval
    end note

    submitted --> terminated : LabRuntimeAgent<br/>(cleanup trigger)
    note right of submitted
        Score sent to PVUE
        Lab session complete
    end note

    terminated --> [*]
    note left of terminated
        • CML instance destroyed
        • Resources cleaned up
        • Post-terminate hooks
    end note

    %% Error transitions
    initializing --> terminated : Initialization failure
    running --> terminated : System error
    grading --> terminated : Grading failure

    classDef startState fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef activeState fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef gradingState fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef endState fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px
    classDef errorState fill:#ffebee,stroke:#c62828,stroke-width:2px

    class scheduled startState
    class pending,initializing,ready_for_user,running activeState
    class ready_for_grading,grading,graded gradingState
    class reviewed,submitted endState
    class terminated errorState
```

## Hook Scripts Override Points

Any Lablet Definition can override the default lifecycle with custom hook scripts:

- **pre-init**: Setup tasks before initialization
- **init**: Custom initialization logic
- **post-init**: Post-initialization validation
- **pre-grade**: Pre-grading preparation
- **grade**: Custom grading logic
- **post-grade**: Post-grading cleanup
- **pre-terminate**: Pre-termination tasks
- **terminate**: Custom termination logic
- **post-terminate**: Final cleanup

## State Transition Triggers

| From State          | To State            | Trigger                           | System/Role           |
| ------------------- | ------------------- | --------------------------------- | --------------------- |
| `[*]`               | `scheduled`         | Candidate starts exam with Lablet | PVUE Driver (ALII S1) |
| `scheduled`         | `pending`           | Calendar/scheduling logic         | Lab Schedule Manager  |
| `pending`           | `initializing`      | Available capacity found          | LabRuntimeAgent       |
| `initializing`      | `ready_for_user`    | Topology and devices ready        | LabOrchestrator       |
| `ready_for_user`    | `running`           | Lab URL requested                 | PVUE Driver (ALII S2) |
| `running`           | `ready_for_grading` | Candidate clicks "Next Item"      | PVUE Driver (ALII S3) |
| `ready_for_grading` | `grading`           | Auto-trigger after S3             | GradingEngine         |
| `grading`           | `graded`            | Evaluation complete               | GradingEngine         |
| `graded`            | `reviewed`          | Quality assurance check           | EPM/Manager           |
| `reviewed`          | `submitted`         | Admin approval                    | LabControlPlaneAPI    |
| `submitted`         | `terminated`        | Cleanup trigger                   | LabRuntimeAgent       |
| `terminated`        | `[*]`               | Final cleanup complete            | System                |

## Notes

- **LabDefinition vs LabInstance**: This state machine applies to individual LabInstance objects (one per candidate per exam attempt)
- **Hook Extensibility**: EPMs can customize behavior at any transition point via hook scripts
- **Error Handling**: Failures at key stages can trigger direct transitions to `terminated` state
- **Resource Management**: States track both logical progress and physical resource allocation/cleanup
