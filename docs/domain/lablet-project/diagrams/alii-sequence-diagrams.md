# ALII Integration Sequence Diagrams

This document shows the sequence of interactions between PVUE, the ALII gateway, and internal Cisco systems for Lablet delivery.

## Current State: perl-LDS Integration

```mermaid
sequenceDiagram
    participant Candidate
    participant PVUE_Driver as PVUE Test Driver
    participant ALII_Gateway as ALII Gateway<br/>(perl-LDS)
    participant Lab_Scheduler as Lab Schedule<br/>Manager
    participant LabOrchestrator
    participant LabRuntimeAgent
    participant CML_Worker as CML Worker
    participant RCU as RCU<br/>(Grading)
    participant SVN as SVN<br/>(Content Repo)

    Note over Candidate, SVN: S1: Initialize Lab Item (Provision)

    Candidate->>PVUE_Driver: Start exam attempt<br/>with Lablet Item

    PVUE_Driver->>+ALII_Gateway: S1: create_lab_item(regId, labName)
    Note right of ALII_Gateway: ALII Protocol<br/>Lab Provisioning

    ALII_Gateway->>Lab_Scheduler: Check scheduling<br/>and availability
    Lab_Scheduler-->>ALII_Gateway: Schedule confirmed

    ALII_Gateway->>LabOrchestrator: Create LabInstance<br/>(scheduled → pending)
    LabOrchestrator->>LabRuntimeAgent: Provision request<br/>(pending → initializing)

    LabRuntimeAgent->>CML_Worker: Create lab topology
    LabRuntimeAgent->>SVN: Fetch lab content<br/>and configurations
    SVN-->>LabRuntimeAgent: Content package

    CML_Worker-->>LabRuntimeAgent: Topology ready
    LabRuntimeAgent-->>LabOrchestrator: Initialization complete<br/>(initializing → ready_for_user)

    LabOrchestrator-->>ALII_Gateway: Lab URL available

    ALII_Gateway-->>-PVUE_Driver: PENDING_INITIALIZATION<br/>(labInstanceId, waitTime: 180s)
    PVUE_Driver-->>Candidate: Please wait...<br/>Lab initializing

    Note over Candidate, SVN: S2: Get Lab Launch URL

    Candidate->>PVUE_Driver: Ready to start lab
    PVUE_Driver->>+ALII_Gateway: S2: get_lab_url(labInstanceId)

    ALII_Gateway->>LabOrchestrator: Trigger state transition<br/>(ready_for_user → running)

    ALII_Gateway-->>-PVUE_Driver: Lab URL response<br/>(https://lds/session_id)
    PVUE_Driver-->>Candidate: Launch lab interface<br/>in embedded iframe

    Note over Candidate, SVN: Lab Session Active

    Candidate->>Candidate: Perform lab tasks<br/>and exercises

    Note over Candidate, SVN: S3: Get/Trigger Grading

    Candidate->>PVUE_Driver: Click "Next Item"<br/>(finished lab)
    PVUE_Driver->>+ALII_Gateway: S3: get_grading_results(labInstanceId)

    ALII_Gateway->>LabOrchestrator: Trigger grading<br/>(running → ready_for_grading)
    LabOrchestrator->>RCU: Start grading process<br/>(ready_for_grading → grading)

    RCU->>CML_Worker: Collect device outputs<br/>and telemetry
    CML_Worker-->>RCU: Device states and logs

    RCU->>RCU: Execute grading scenarios<br/>and rubric evaluation
    RCU-->>LabOrchestrator: ScoreReport generated<br/>(grading → graded)

    LabOrchestrator-->>ALII_Gateway: Grading complete<br/>with score

    ALII_Gateway-->>-PVUE_Driver: Score response<br/>(itemScore, itemResponses)
    PVUE_Driver-->>Candidate: Show results<br/>Continue to next item

    Note over Candidate, SVN: S4: Cleanup (Optional)

    ALII_Gateway->>LabOrchestrator: Cleanup trigger<br/>(submitted → terminated)
    LabOrchestrator->>LabRuntimeAgent: Terminate lab instance
    LabRuntimeAgent->>CML_Worker: Destroy lab topology
    CML_Worker-->>LabRuntimeAgent: Cleanup complete
```

## Future State: pyLDS + Mozart Integration

```mermaid
sequenceDiagram
    participant Candidate
    participant PVUE_Driver as PVUE Test Driver
    participant PVUE_Gateway as PVUE Gateway<br/>(ALII API)
    participant Mozart as Mozart<br/>(Orchestration)
    participant Synapse as Synapse<br/>(Workflow)
    participant pyLDS as pyLDS<br/>(Lab Delivery)
    participant LabController as Lablet<br/>Controller
    participant MinIO as MinIO<br/>(Content S3)

    Note over Candidate, MinIO: S1: Initialize Lab Item (Future Architecture)

    Candidate->>PVUE_Driver: Start exam attempt<br/>with Lablet Item

    PVUE_Driver->>+PVUE_Gateway: S1: create_lab_item(regId, labName)
    Note right of PVUE_Gateway: Next-gen ALII<br/>Implementation

    PVUE_Gateway->>Mozart: create_workflow_instance<br/>(pvue_lablet_create:latest)
    Mozart->>Synapse: Execute lablet<br/>provisioning workflow

    Synapse->>pyLDS: create_new_session_with_part(labName)
    pyLDS-->>Synapse: ack(session_id, lab_url)

    Synapse->>PVUE_Gateway: post_lab_item_url<br/>(lab_url)
    PVUE_Gateway->>PVUE_Gateway: store_lab_item_url<br/>(mapping maintenance)

    Synapse->>LabController: instantiate_lablet_topology<br/>(regId, labName)
    LabController->>MinIO: pull_lab_content<br/>(topology + configs)
    MinIO-->>LabController: Content package

    LabController->>LabController: create_lablet_pod<br/>start_lablet_pod
    LabController-->>Synapse: ack(devices_info)

    Synapse->>pyLDS: set_devices(session_id, devices_info)
    pyLDS-->>Synapse: ack(session_id, lab_url)

    Synapse->>PVUE_Gateway: mark_lab_item_initialized(lablet_id)
    PVUE_Gateway->>PVUE_Gateway: set_lab_item_status<br/>(INITIALIZED)

    PVUE_Gateway-->>-PVUE_Driver: INITIALIZED<br/>(labInstanceId, lab_url)
    PVUE_Driver-->>Candidate: Lab ready!<br/>Click to launch

    Note over Candidate, MinIO: S2 & S3: Streamlined in Future State

    Note right of PVUE_Gateway: Future architecture combines<br/>S2 and S3 into more<br/>efficient workflow
```

## Key Differences: Current vs Future

| Aspect               | Current (perl-LDS + SVN)    | Future (pyLDS + Mozart)      |
| -------------------- | --------------------------- | ---------------------------- |
| **Content Storage**  | SVN (centralized)           | MinIO/S3 (object storage)    |
| **Orchestration**    | Manual coordination         | Mozart workflow automation   |
| **State Management** | Distributed across services | Centralized in PVUE Gateway  |
| **Performance**      | Multi-step S1→S2→S3 calls   | Streamlined single workflow  |
| **Scalability**      | Limited by SVN bottleneck   | Cloud-native elastic scaling |
| **Monitoring**       | Basic logging               | Comprehensive telemetry      |

## ALII Protocol Reference

| Call   | Purpose                  | Current Implementation          | Future Implementation           |
| ------ | ------------------------ | ------------------------------- | ------------------------------- |
| **S1** | Initialize/Provision lab | perl-LDS + manual orchestration | PVUE Gateway + Mozart workflows |
| **S2** | Get lab launch URL       | Direct perl-LDS query           | Embedded in S1 response         |
| **S3** | Trigger grading          | RCU + manual coordination       | Automated grading pipeline      |
| **S4** | Cleanup (optional)       | Manual cleanup scripts          | Automated resource lifecycle    |

## Error Handling Patterns

Both architectures handle common failure scenarios:

- **Capacity exhaustion**: Queue requests with estimated wait times
- **Initialization failures**: Retry with exponential backoff
- **Grading timeouts**: Fallback to manual review process
- **Network failures**: Circuit breaker pattern with degraded service
