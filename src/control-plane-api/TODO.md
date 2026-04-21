# TODO

- [ ] Fix "Delete LabRecord" to support stop-wipe-delete instead of just POST /delete
- [ ] Add "Delete LabletDefinition" command
- [ ] Add "Dispose Orphaned Labs" command full stack (button in Labs view)
- [ ] Ensure that "Refresh" buttons in frontend do trigger relevant reconciliation loops in backend as user-triggered (unless upcoming within 10s by automated polling), applicable to workers, labs, sessions
- [ ] Successful extend_session on the UI fails to remove the warning banner
- [ ] Add lifecycle triggers based on cloudevent' attributes and time-based correlations (identify the application.integration.events' handler, in/out schemas, side-effects per pipeline step?)

- [x] Fix SSE Realtime for ALL Aggregates — eventMap already covers all aggregate events (workers, sessions, definitions, lab records, templates). Verified coverage.
- [ ] Fix SSE blocking backend auto-reload still not working after Added `_shutdown_event` (asyncio.Event) to SSEEventRelay. EventsController generator loop now awaits shutdown_event alongside queue and disconnect, breaking immediately on app shutdown. SSEEventRelayHostedService.stop_async() sets the event before broadcasting.
- [ ] Fix Tag CRUD full stack
- [ ] add user profile modal
- [ ] add indicator of when will the next discovery happen (ideally, a decreasing progressbar illustrating countdown) to (worker & lablet) instances view

## Features

- [ ] Add autonomous recurrent LabletInstance discovery/import/sync for all known Workers
- [ ] Track and display LabletDefinition' revision (state_version) and last_updated
- [ ] Add CRUD for Worker~, LabRecords and LabletDefinitions to UI restricted to admin users
- [ ] Extend and reinforce RBAC with scopes for fine permissions (per track claims, per role functions)
- [ ] Add API rate-limiting
- [ ] Limit SSE per authenticated user session
