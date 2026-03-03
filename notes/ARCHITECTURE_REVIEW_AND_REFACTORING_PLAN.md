# Architecture Review & Refactoring Plan

**Date:** November 21, 2025
**Status:** Draft
**Priority:** High

## Executive Summary

A comprehensive architectural review of the `lablet-cloud-manager` backend has identified critical scalability and reliability issues. The most urgent concern is the use of blocking I/O in asynchronous contexts, which severely limits throughput. Additionally, the `CMLWorker` aggregate has grown into a "God Object," and the distributed transaction handling for worker creation is prone to leaving orphaned resources.

This document outlines the findings and a phased implementation plan to address these issues, moving towards a cleaner DDD/CQRS architecture.

## Critical Findings

### 1. Performance Bottleneck: Blocking I/O in Async Code

- **Issue:** The `AwsEc2Client` uses synchronous `boto3` calls (e.g., `create_instances`, `describe_images`) directly within `async` methods.
- **Impact:** This blocks the main event loop. During an AWS API call (which can take seconds), the entire application freezes, unable to process other requests or heartbeats.
- **Severity:** **CRITICAL**

### 2. Distributed Transaction Risks (Zombie Resources)

- **Issue:** `CreateCMLWorkerCommandHandler` performs a remote side-effect (AWS EC2 creation) _before_ ensuring the local state is persisted safely, and without a compensation mechanism.
- **Impact:** If the database save fails after EC2 provisioning, the system creates a "zombie" instance in AWS that the application tracks nowhere.
- **Severity:** **HIGH**

### 3. Domain Model Violation: "God Aggregate"

- **Issue:** `CMLWorker` violates the Single Responsibility Principle by managing infrastructure state, application metrics, licensing, and idle logic all in one massive class.
- **Impact:** High coupling, difficult testing, and "Leaky Abstractions" where infrastructure details (parsing raw API dicts) bleed into the domain.
- **Severity:** **MEDIUM**

### 4. Inconsistent Job Orchestration

- **Issue:**
  - `ActivityDetectionJob` fetches _all_ workers (inefficient) and processes them sequentially (slow).
  - `WorkerMetricsCollectionJob` bypasses the DI container, manually instantiating repositories, leading to potential configuration drift.
- **Impact:** Poor scalability as the number of workers increases; maintenance headaches due to duplicated setup logic.
- **Severity:** **MEDIUM**

### 5. Fragile Idle Detection

- **Issue:** Idle detection relies solely on `cml_labs_count > 0`, ignoring active user editing sessions. The implementation uses a "Chatty Mediator" pattern, chaining multiple commands/queries unnecessarily.
- **Impact:** False positives in auto-pausing; unnecessary complexity in the command chain.
- **Severity:** **MEDIUM**

---

## Implementation Plan

### Phase 1: Critical Stability & Performance (Immediate)

**Goal:** Unblock the event loop and fix immediate concurrency issues.

1. **Fix Blocking I/O in `AwsEc2Client`** (✅ Completed)
    - **Action:** Wrap all `boto3` calls in `asyncio.get_event_loop().run_in_executor(None, ...)` or migrate to `aioboto3`.
    - **Target:** `src/integration/services/aws_ec2_api_client.py`

2. **Optimize Background Jobs** (✅ Completed)
    - **Action:** Refactor `ActivityDetectionJob` to use `repository.get_active_workers_async()` and `asyncio.Semaphore` for concurrent processing (matching `WorkerMetricsCollectionJob`).
    - **Action:** Fix `WorkerMetricsCollectionJob` to properly use the `service_provider` scope instead of manual instantiation.
    - **Target:** `src/application/jobs/activity_detection_job.py`, `src/application/jobs/worker_metrics_collection_job.py`

### Phase 2: Data Integrity & Reliability

**Goal:** Ensure no resources are orphaned and error handling is robust.

3. **Implement Saga Pattern for Worker Creation** (✅ Completed)
    - **Action:** Refactor `CreateCMLWorkerCommandHandler`.
        1. Create `CMLWorker` in DB (Status: `PENDING`).
        2. Publish `CMLWorkerCreatedDomainEvent`.
        3. Create `ProvisionCMLWorkerEventHandler` to call AWS.
        4. On success: Update to `PROVISIONED`.
        5. On failure: Update to `FAILED` and trigger cleanup.
    - **Target:** `src/application/commands/create_cml_worker_command.py`

4. **Refactor `SyncWorkerCMLDataCommandHandler`** (✅ Completed)
    - **Action:** Simplify the nested try/except blocks. Introduce a `CMLHealthService` or similar helper that returns a consolidated health result object.
    - **Target:** `src/application/commands/sync_worker_cml_data_command.py`

### Phase 3: Domain Refactoring (Long-term)

**Goal:** Clean DDD architecture and better separation of concerns.

5. **Decompose `CMLWorker` Aggregate**
    - **Action:** Extract `CMLMetrics` and `CMLLicense` into separate Value Objects or Entities.
    - **Action:** Move raw dictionary parsing logic out of the entity and into the Anti-Corruption Layer (ACL) or Mapper.
    - **Target:** `src/domain/entities/cml_worker.py`

6. **Improve Idle Detection Logic**
    - **Action:** Create a Domain Service `IdleDetectionService` that encapsulates the rules for "idleness" (checking labs, user sessions, etc.).
    - **Action:** Simplify `DetectWorkerIdleCommand` to use this service directly.
