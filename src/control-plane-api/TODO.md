# TODO

- [ ] Add "Delete LabletDefinition" command
- [ ] Add "Dispose Orphaned Labs" command full stack (button in Labs view)
- [ ] Ensure that "Refresh" buttons in frontend do trigger relevant reconciliation loops in backend as user-triggered (unless upcoming within 10s by automated polling), applicable to workers, labs, sessions
- [ ] Add lifecycle triggers based on cloudevent' attributes and time-based correlations (identify the application.integration.events' handler, in/out schemas, side-effects per pipeline step?)

## Fix

- [ ] Fix Tag CRUD full stack
- [x] Fix SSE Realtime for ALL Aggregates — eventMap already covers all aggregate events (workers, sessions, definitions, lab records, templates). Verified coverage.
- [x] Fix SSE blocking backend auto-reload — Added `_shutdown_event` (asyncio.Event) to SSEEventRelay. EventsController generator loop now awaits shutdown_event alongside queue and disconnect, breaking immediately on app shutdown. SSEEventRelayHostedService.stop_async() sets the event before broadcasting.
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
