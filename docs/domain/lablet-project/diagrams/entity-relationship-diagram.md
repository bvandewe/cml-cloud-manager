# Entity Relationship Diagram - Lablet Resources Manager

This diagram shows the data model relationships for the Lablet Resources Manager implementing the ROLAP (Resources-Oriented) architecture.

## Core Resource Entities & Relationships

### Lablet Resources Manager - Data Model

```mermaid
erDiagram
    %% Core Resource Entities
    LABDEFINITION ||--o{ LABINSTANCE : instantiates
    LABDEFINITION {
        string name PK "Unique lablet identifier"
        string uid "System-generated UUID"
        integer revision "Immutable version number"
        datetime creationTimestamp
        object topology "CML nodes and links definition"
        object defaultResources "CPU and RAM defaults"
        object lifecycleDefaults "Hook scripts configuration"
        string status "Published, Draft, Archived"
    }

    LABINSTANCE ||--o{ GRADINGSESSION : evaluated_by
    LABINSTANCE }o--|| RUNTIMEPROFILE : uses
    LABINSTANCE {
        string name PK "Instance identifier"
        string uid "System-generated UUID"
        string labDefinitionName FK "Reference to LabDefinition"
        string runtimeProfile "Optional profile override"
        string resourceVersion "Optimistic concurrency control"
        datetime creationTimestamp
        object requestedResources "CPU and RAM requirements"
        object lifecycleHooks "Custom hook overrides"
        string phase "Pending, Running, Grading, etc."
        string currentWorker "Assigned CML worker node"
        string cmlInstanceId "CML system identifier"
        object conditions "Status conditions array"
        object endpoints "Lab access URLs"
    }

    GRADINGSESSION ||--|| SCOREREPORT : produces
    GRADINGSESSION ||--o{ DEVICEOUTPUT : aggregates
    GRADINGSESSION {
        string name PK "Session identifier"
        string uid "System-generated UUID"
        string labInstanceName FK "Reference to LabInstance"
        string resourceVersion
        datetime creationTimestamp
        string[] scenarios "Grading scenarios to execute"
        integer timeoutSeconds "Maximum grading duration"
        string phase "Pending, Running, Completed, Failed"
        string scoreReportName "Generated report reference"
        string activeScenario "Currently executing scenario"
    }

    SCOREREPORT {
        string name PK "Report identifier"
        string uid "System-generated UUID"
        string gradingSessionName FK "Reference to GradingSession"
        datetime creationTimestamp
        datetime generatedAt "Report generation timestamp"
        float score "Achieved score"
        float maxScore "Maximum possible score"
        object rubricBreakdown "Detailed scoring breakdown"
    }

    CMLWORKER ||--o{ LABINSTANCE : hosts
    CMLWORKER {
        string name PK "Worker node identifier"
        string uid "System-generated UUID"
        datetime lastReportTime "Heartbeat timestamp"
        string resourceVersion
        integer totalCpu "Total CPU capacity"
        integer totalRamGb "Total RAM capacity"
        string phase "Online, Offline, Maintenance"
        integer allocatedCpu "Currently allocated CPU"
        integer allocatedRamGb "Currently allocated RAM"
        integer labCount "Number of hosted labs"
        object pressure "Resource pressure metrics"
    }

    RUNTIMEPROFILE {
        string name PK "Profile identifier"
        string uid "System-generated UUID"
        datetime creationTimestamp
        string resourceVersion
        object cpuLimits "Min and max CPU constraints"
        object memoryLimitsGb "Min and max RAM constraints"
        string region "Geographic region preference"
        string workerPool "Worker pool assignment"
        object schedulingHints "Scheduling preferences"
    }

    DEVICEOUTPUT {
        string name PK "Output identifier"
        string labInstanceName FK "Reference to LabInstance"
        string deviceId "CML device identifier"
        datetime timestamp "Collection timestamp"
        string command "Command that generated output"
        string contentRef "Object storage path"
        string contentType "MIME type of output"
        integer sizeBytes "Output size"
        string checksum "Content verification hash"
    }

    %% External System Integrations
    PVUE_REGISTRATION ||--o{ LABINSTANCE : triggers
    PVUE_REGISTRATION {
        string regId PK "PVUE registration ID"
        string candidateId "Candidate identifier"
        string examId "Exam session identifier"
        datetime scheduledTime "Lab scheduled start time"
        string labDefinitionName FK "Requested lab definition"
        string status "Scheduled, Active, Completed"
    }

    %% Operational Entities
    EXAM_TRACK ||--o{ LABDEFINITION : contains
    EXAM_TRACK {
        string trackCode PK "DEVASC, SCOR, CLCOR, etc."
        string trackName "Full certification name"
        string trackLevel "Associate, Professional, Expert"
        string epmOwner "Responsible EPM"
        object blueprint "Curriculum requirements"
        datetime lastUpdated
    }

    EXAM_FORM ||--o{ LABDEFINITION : includes
    EXAM_FORM {
        string formId PK "Exam form identifier"
        string trackCode FK "Associated exam track"
        integer version "Form version number"
        object itemSequence "Lab item ordering"
        datetime effectiveDate
        datetime expirationDate
        string status "Active, Retired, Development"
    }

    %% Many-to-many relationships through junction tables
    EXAM_TRACK ||--o{ TRACK_DEFINITION : contains
    LABDEFINITION ||--o{ TRACK_DEFINITION : belongs_to
    TRACK_DEFINITION {
        string trackCode FK "Reference to ExamTrack"
        string labDefinitionName FK "Reference to LabDefinition"
        integer sequenceOrder "Order within track"
        boolean required "Mandatory vs optional"
        float weightPercentage "Scoring weight"
    }

    EXAM_FORM ||--o{ FORM_ITEM : includes
    LABDEFINITION ||--o{ FORM_ITEM : appears_in
    FORM_ITEM {
        string formId FK "Reference to ExamForm"
        string labDefinitionName FK "Reference to LabDefinition"
        integer position "Position in exam"
        object parameters "Form-specific parameters"
        datetime addedDate
    }

    %% Content Management Relationships
    CONTENT_PACKAGE ||--|| LABDEFINITION : defines
    CONTENT_PACKAGE {
        string packageId PK "Content package identifier"
        string labDefinitionName FK "Associated lab definition"
        string version "Content version"
        string sourceSystem "Mosaic, CML Dev, etc."
        object topology "CML topology JSON"
        object instructions "Lab instructions content"
        object verifications "Grading verifications"
        object images "Required CML images"
        datetime lastModified
        string status "Draft, Reviewed, Published"
    }

    IMAGE_REGISTRY ||--o{ CONTENT_PACKAGE : provides_images
    IMAGE_REGISTRY {
        string imageId PK "CML image identifier"
        string imageName "Human-readable name"
        string version "Image version"
        string nodeType "Router, Switch, Server, etc."
        string platform "IOS-XE, NX-OS, Ubuntu, etc."
        integer sizeGB "Image size in GB"
        datetime buildDate
        string buildStatus "Available, Building, Failed"
        object metadata "Image metadata and capabilities"
    }

    %% Styling for different entity types
    classDef coreEntity fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef operationalEntity fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef integrationEntity fill:#fff3e0,stroke:#ef6c00,stroke-width:2px
    classDef contentEntity fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    classDef junctionEntity fill:#fafafa,stroke:#616161,stroke-width:1px

    class LABDEFINITION,LABINSTANCE,GRADINGSESSION,SCOREREPORT,CMLWORKER,RUNTIMEPROFILE,DEVICEOUTPUT coreEntity
    class EXAM_TRACK,EXAM_FORM operationalEntity
    class PVUE_REGISTRATION integrationEntity
    class CONTENT_PACKAGE,IMAGE_REGISTRY contentEntity
    class TRACK_DEFINITION,FORM_ITEM junctionEntity
```

## Relationship Details & Cardinalities

### Core Resource Relationships

| From Entity    | Relationship | To Entity      | Cardinality | Description                                     |
| -------------- | ------------ | -------------- | ----------- | ----------------------------------------------- |
| LabDefinition  | instantiates | LabInstance    | 1:N         | One definition can create many instances        |
| LabInstance    | evaluated_by | GradingSession | 1:N         | One instance can have multiple grading attempts |
| GradingSession | produces     | ScoreReport    | 1:1         | Each session produces exactly one report        |
| GradingSession | aggregates   | DeviceOutput   | 1:N         | Sessions collect multiple device outputs        |
| LabInstance    | uses         | RuntimeProfile | N:1         | Many instances can share a profile              |
| CMLWorker      | hosts        | LabInstance    | 1:N         | Workers can host multiple lab instances         |

### Operational Relationships

| From Entity       | Relationship | To Entity     | Description                        |
| ----------------- | ------------ | ------------- | ---------------------------------- |
| ExamTrack         | contains     | LabDefinition | Via TrackDefinition junction table |
| ExamForm          | includes     | LabDefinition | Via FormItem junction table        |
| PVUE Registration | triggers     | LabInstance   | External ALII integration point    |

### Content Management Relationships

| From Entity    | Relationship    | To Entity      | Description                               |
| -------------- | --------------- | -------------- | ----------------------------------------- |
| ContentPackage | defines         | LabDefinition  | 1:1 mapping of content to lab definitions |
| ImageRegistry  | provides_images | ContentPackage | N:M through image dependencies            |

## Key Design Principles

### 1. Immutability Patterns

- **LabDefinition.revision**: Once referenced by a LabInstance, cannot be changed
- **ScoreReport**: Write-once, immutable after generation
- **DeviceOutput**: Append-only evidence collection

### 2. Declarative Spec/Status Pattern

- **Spec fields**: User-declared desired state (immutable after creation)
- **Status fields**: Controller-managed observed state (continuously updated)
- **ResourceVersion**: Optimistic concurrency control

### 3. Reference Integrity

- **LabInstance.labDefinitionName**: Immutable reference to specific LabDefinition
- **Foreign key constraints**: Enforced at application level with validation
- **Cascade policies**: Defined per relationship (e.g., delete LabInstance cascades to GradingSession)

### 4. Lifecycle State Management

- **Phase enumerations**: Controlled state transitions (scheduled → pending → initializing → ...)
- **Condition arrays**: Detailed status tracking with timestamps and reasons
- **Reconciliation**: Controllers detect drift and converge toward desired state

## Data Storage Strategy

### Primary Storage (etcd)

- All core resources stored as JSON documents
- Watch-based event distribution for real-time updates
- Optimistic concurrency via resourceVersion

### Object Storage (MinIO/S3)

- **DeviceOutput.contentRef**: Large output files stored separately
- **ContentPackage**: Lab topology and instruction content
- **ImageRegistry**: CML image files and metadata

### Caching Strategy

- **LabControlPlaneAPI**: In-memory cache of frequently accessed resources
- **TTL policies**: Automatic cache invalidation based on resourceVersion
- **Event-driven updates**: etcd watch feeds cache invalidation

## Migration Considerations

### Current State (perl-LDS + SVN)

- Content stored in SVN with file-based organization
- Lab state managed in perl-LDS database tables
- Manual synchronization between systems

### Future State (pyLDS + Mozart)

- All resources in cloud-native object storage
- Event-driven architecture with automatic reconciliation
- Unified data model across all components

This entity model supports both current and future architectures with abstraction layers handling the storage implementation differences.
