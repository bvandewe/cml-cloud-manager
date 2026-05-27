# Sprint 5: Phase 5 — Grading Integration

> **Effort:** 3–4 sessions
> **Dependencies:** Sprint 3 (resource hierarchy complete)
> **Services:** lablet-controller, control-plane-api, lcm-core
> **Status:** ⬜ Not Started
> **Critical Path:** This is the last major MVP feature

## Objective

Implement the full grading lifecycle: evidence collection from CML labs, grading computation, score recording, and pipeline run archival. This completes the `COLLECTING → GRADING → SCORED` state flow that was unblocked by Phase 7 (Session Entity Model).

## Architecture Context

The grading flow is a multi-step pipeline orchestrated by the lablet-controller reconciler:

```
Session RUNNING → timeslot_end reached
  → Pipeline: collect_evidence
    → Step: stop_lab (graceful)
    → Step: extract_configs (CML API)
    → Step: capture_screenshots (CML API)
    → Step: package_evidence (archive to S3)
  → Pipeline: compute_grading
    → Step: load_rubric (from definition)
    → Step: evaluate_evidence (grading SPI)
    → Step: record_score (CPA command)
    → Step: notify_result (CloudEvent)
  → Session transitions to SCORED
```

The `PipelineExecutor` (ADR-034) and step handler registry (ADR-038) are already implemented. This sprint adds the **grading-specific step handlers** and the **GradingSPI client**.

## Tasks

### S5.1 — Implement GradingSPI Client

**Scope:**

- [ ] Create `GradingSPIClient` in lablet-controller's integration layer
- [ ] Interface: `evaluate_evidence(evidence_package, rubric) → GradingResult`
- [ ] Initial implementation: simple rule-based evaluator (no external service yet)
- [ ] Configuration: `GRADING_SPI_URL`, `GRADING_SPI_ENABLED` settings
- [ ] Add retry logic with exponential backoff

**Pattern Reference:** Follow `CMLSPIClient` pattern for HTTP client structure.

**Files to create:**

- `src/lablet-controller/integration/services/grading_spi_client.py`
- `src/lablet-controller/integration/models/grading_models.py` (request/response DTOs)
- `src/lablet-controller/config/settings.py` (add grading settings)

---

### S5.2 — Implement Evidence Collection Step Handlers

**Scope:**

- [ ] `StepExtractConfigs`: Extract running configs from CML nodes via CML API
- [ ] `StepCaptureState`: Capture lab state, node states, link states
- [ ] `StepPackageEvidence`: Bundle evidence into structured archive
- [ ] Register handlers in step handler registry
- [ ] Each handler follows `PipelineStepHandler` protocol

**Pattern Reference:** Follow existing step handlers in `application/pipeline_steps/`.

**Files to create:**

- `src/lablet-controller/application/pipeline_steps/step_extract_configs.py`
- `src/lablet-controller/application/pipeline_steps/step_capture_state.py`
- `src/lablet-controller/application/pipeline_steps/step_package_evidence.py`

**Acceptance Criteria:**

- Evidence package contains: node configs, lab topology, node states, timestamps
- Steps emit progress events for SSE pipeline panel
- Tests: 3+ per handler (happy path, CML API error, empty lab)

---

### S5.3 — Implement Grading Step Handlers

**Scope:**

- [ ] `StepLoadRubric`: Load grading rubric from LabletDefinition
- [ ] `StepEvaluateEvidence`: Call GradingSPI with evidence + rubric
- [ ] `StepRecordScore`: Call CPA to record score on LabletSession via command
- [ ] `StepNotifyResult`: Emit CloudEvent with grading result

**Files to create:**

- `src/lablet-controller/application/pipeline_steps/step_load_rubric.py`
- `src/lablet-controller/application/pipeline_steps/step_evaluate_evidence.py`
- `src/lablet-controller/application/pipeline_steps/step_record_score.py`
- `src/lablet-controller/application/pipeline_steps/step_notify_result.py`

---

### S5.4 — Add COLLECTING → GRADING → SCORED State Flow in CPA

**Scope:**

- [ ] Add `RecordScoreCommand` + handler (receives score from lablet-controller)
- [ ] Add `ScoreRecordedDomainEvent` to LabletSession aggregate
- [ ] Add score-related fields to `GradingSession` child entity
- [ ] Wire state transitions: COLLECTING → GRADING → SCORED
- [ ] Update session DTOs to include score data
- [ ] Add `GetSessionScoreQuery` for retrieving scores

**Files to create/modify:**

- `src/control-plane-api/application/commands/session/record_score_command.py` (create or verify exists)
- `src/control-plane-api/domain/entities/lablet_session.py` (state transitions)
- `src/control-plane-api/domain/events/` (score events)
- `src/control-plane-api/application/dtos/session_dtos.py` (score fields)

---

### S5.5 — Pipeline Run Storage on LabRecord (Sprint F Completion)

**Scope:**

- [ ] Append `PipelineRunRecord` to LabRecord aggregate on pipeline completion
- [ ] Store: pipeline_name, steps_executed, duration, outcome, error_details
- [ ] Add `GetLabRecordPipelineHistoryQuery` for retrieving run history
- [ ] Display pipeline run history in LabRecord Details modal (frontend)

**Pattern Reference:** `PipelineRunRecord` VO already exists (Sprint F of ADR-034). Wire storage into pipeline executor completion callback.

**Files:**

- `src/control-plane-api/domain/entities/lab_record.py` (aggregate method)
- `src/control-plane-api/application/commands/lab_record/record_pipeline_run_command.py`
- `src/control-plane-api/application/queries/` (history query)
- Frontend: LabRecord Details modal — pipeline history tab

---

### S5.6 — SSE Events for Definition Lifecycle

**Scope:**

- [ ] Add SSE event types for definition status changes:
  - `definition.created`, `definition.syncing`, `definition.ready`, `definition.archived`
- [ ] Wire domain events to SSE relay in CPA
- [ ] Add `sseAdapter.ts` mappings for definition events
- [ ] Update definitions store to handle SSE-driven updates

**Files:**

- `src/control-plane-api/application/services/sse_event_relay.py`
- `src/control-plane-api/static/src/services/sseAdapter.ts`
- `src/control-plane-api/static/src/stores/definitionSlice.ts`

---

## Acceptance Criteria (Sprint-Level)

- [ ] Full pipeline execution: evidence collection → grading → score recording
- [ ] Session transitions through COLLECTING → GRADING → SCORED states
- [ ] Scores visible in Session Details modal
- [ ] Pipeline run history visible in LabRecord Details modal
- [ ] Definition SSE events working end-to-end
- [ ] `make test` passes (lablet-controller + CPA)
- [ ] New tests: 25+ across all tasks
- [ ] Commits: one per task (`feat: S5.1 — grading SPI client`, etc.)
- [ ] Update `IMPLEMENTATION_STATUS.md` → Phase 5 ✅
