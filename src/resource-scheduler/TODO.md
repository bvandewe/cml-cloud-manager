# TODO — Resource Scheduler

## Priority 1: TimeslotManager (Sprint H) — ✅ Complete

- [x] **H1: TimeslotManagerHostedService** — Leader-elected background service that gates PENDING sessions by timeslot proximity
  - Runs on configurable interval (default 60s)
  - Queries CPA for PENDING sessions with `timeslot_start` within `timeslot_lead_time_minutes` window
  - Writes etcd trigger keys to activate SchedulerHostedService watch for timeslot-eligible sessions
  - Detects PENDING sessions whose `timeslot_start` has passed → calls CPA to expire them
  - Follows CleanupHostedService pattern (leader election, asyncio loops, DI factory)
- [x] **H2: Timeslot-aware filtering in SchedulerHostedService** — Enhance `list_resources()` to filter out sessions outside timeslot window
  - Skip PENDING sessions with `timeslot_start` > now + `timeslot_lead_time_minutes`
  - Prioritize sessions by timeslot proximity (closest first)
  - Reject/expire sessions with `timeslot_start` < now (already passed, unscheduled)
- [x] **H3: Admin query endpoints** — Timeslot visibility for operators
  - `GET /api/admin/timeslots/approaching` — PENDING sessions entering scheduling window
  - `GET /api/admin/timeslots/expired` — Sessions with expired timeslots
  - `GET /api/admin/timeslots/landscape` — Overview of timeslot distribution (next 24h histogram)
- [x] **H4: Settings** — Add `TIMESLOT_MANAGER_ENABLED`, `TIMESLOT_MANAGER_INTERVAL_SECONDS`, `TIMESLOT_EXPIRY_GRACE_MINUTES`
- [x] **H5: Tests** — Unit tests for TimeslotManagerHostedService, enhanced SchedulerHostedService, admin endpoints
- [x] **H6: Documentation** — ADR-037 for timeslot management decision, resource-scheduler README updated

## Priority 2: Operational Improvements

- [ ] The assigned worker MUST support ALL cml.yml:nodes[].node_definition and .image_deifnition (if defined)

- [ ] Fix and expand resource-scheduler UI dashboard (scheduling metrics, pending/scheduled queues, timeslot landscape)
- [ ] Add OTel metrics for timeslot management (approaching count, expired count, scheduling latency by timeslot proximity)
- [ ] Add placement decision audit log (persist scheduling decisions with timestamps and reasoning)

## Priority 3: Future

- [ ] Add preemption support — reschedule lower-priority sessions to make room for urgent timeslot-approaching sessions
- [ ] Add capacity forecasting — predict worker availability based on timeslot_end of running sessions
