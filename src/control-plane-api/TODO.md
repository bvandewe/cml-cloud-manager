# TODO

## Fix

- [ ] EventBus.ts:247 [EventBus] Error in handler for "lablet.definition.content_synced": TypeError: TOAST: Option "delay" provided type "function" but expected type "number".
    at a (notifications.js:54:19)
    at Object.handler (sseAdapter.js:385:17)
    at a (EventBus.ts:245:40)
    at async i (EventBus.ts:450:17)
    at async sseAdapter.js:99:13
    at async i (EventBus.ts:448:17)


- [ ] labletsession reconciliation:

```
# lablet-controller:

2026-02-28 16:04:15,657 - WARNING - [reconciliation_hosted_service.py:395] - lablet-controller: 4d1bc380-ddac-48d0-a0b4-838e73878cc8 failed (attempt 1): Session 4d1bc380-ddac-48d0-a0b4-838e73878cc8 has no worker_id in pending state. Retry in 1.0s

2026-02-28 16:04:15,915 - DEBUG - [watch_triggered_hosted_service.py:249] - lablet-controller: Watch event: PUT /lcm/sessions/4d1bc380-ddac-48d0-a0b4-838e73878cc8/state (value=SCHEDULED)

2026-02-28 16:04:15,924 - INFO - [lablet_reconciler.py:294] - Watch event: PUT for session 4d1bc380-ddac-48d0-a0b4-838e73878cc8 (new_state=SCHEDULED)

2026-02-28 16:04:15,925 - DEBUG - [watch_triggered_hosted_service.py:249] - lablet-controller: Watch event: PUT /lcm/sessions/4d1bc380-ddac-48d0-a0b4-838e73878cc8/metadata (value={"worker_id": "d75863ec-7934-4517-bd32-97e9dfa8cc96", "allocated_ports": {}, "scheduled_at": "2026-02-28T16:04:15.844624+00:00Z"})

2026-02-28 16:04:15,925 - INFO - [lablet_reconciler.py:294] - Watch event: PUT for session 4d1bc380-ddac-48d0-a0b4-838e73878cc8 (new_state={"worker_id": "d75863ec-7934-4517-bd32-97e9dfa8cc96", "allocated_ports": {}, "scheduled_at": "2026-02-28T16:04:15.844624+00:00Z"})

2026-02-28 16:04:16,426 - INFO - [watch_triggered_hosted_service.py:278] - lablet-controller: Watch-triggered reconcile for 1 resources: ['4d1bc380-ddac-48d0-a0b4-838e73878cc8']

2026-02-28 16:04:16,543 - DEBUG - [lablet_reconciler.py:381] - Reconciling session 4d1bc380-ddac-48d0-a0b4-838e73878cc8 (status=scheduled)

2026-02-28 16:04:16,593 - ERROR - [lablet_reconciler.py:424] - Error reconciling session 4d1bc380-ddac-48d0-a0b4-838e73878cc8: can't subtract offset-naive and offset-aware datetimes

Traceback (most recent call last):

  File "/app/application/hosted_services/lablet_reconciler.py", line 410, in reconcile

    return await self._handle_scheduled(instance)

           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

  File "/app/application/hosted_services/lablet_reconciler.py", line 463, in _handle_scheduled

    time_until_start = (timeslot_start - now).total_seconds()

                        ~~~~~~~~~~~~~~~^~~~~

TypeError: can't subtract offset-naive and offset-aware datetimes

2026-02-28 16:04:16,597 - WARNING - [reconciliation_hosted_service.py:395] - lablet-controller: 4d1bc380-ddac-48d0-a0b4-838e73878cc8 failed (attempt 2): can't subtract offset-naive and offset-aware datetimes. Retry in 2.0s

2026-02-28 16:05:15,386 - INFO - [lab_discovery_service.py:139] - 🔄 Starting lab discovery run #35

```

## Bugs

- [ ] Fix Tag CRUD full stack
- [ ] Fix SSE Realtime for ALL Aggregates
- [ ] Fix SSE blocking backend auto-reload
- [ ] successful extend_session on the UI fails to remove the warning banner
- [ ] add user profile modal
- use same UI styling and layout as AIX svcs
- add proper state-manager and event-bus to UI (Cf. AIX svcs)
- add indicator of next discovery timestamp to (worker & lablet) instances view

## Features

- [ ] Add autonomous recurrent LabletInstance discovery/import/sync for all known Workers
- [ ] Track and display LabletDefinition' revision (state_version) and last_updated
- [ ] Add CRUD for Worker~ and LabletDefinitions to UI restricted to admin users
- [ ] Add "New Instance" button to create LabletInstance
- [ ] Add consistent table/card view modes to all Aggregates
- [ ] Rework and simplify the UI to tabbed layout
- [ ] Extend and reinforce RBAC with scopes for fine permissions (per track claims, per role functions)
- [ ] Improve SSE protocol to support all Aggregates
- [ ] Add API rate-limiting
- [ ] Limit SSE per authenticated user session
