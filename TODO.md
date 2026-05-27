# TODO

- [ ] Fix LabRecord vs LabletSession binding (must appear from both sides in UI: Workers' and Labs' "Linked Lablets" as well as Sessions's "No lablet bindings yet.")
- [ ] Use Worker.name instead of worker.id in Lab Records' table and details views (set the worker id in an info icon' s tool tip using bootstrap tooltip)
- [ ] Add "Allocated Ports" to Worker Details modal > Labs > perLab ports
- [ ] Add "LabRecord decision" to the "Placement Preview" command to show the resulting LabRecord (whether matched to existing or create new)
- [ ] Add clear activity indicator to "Lablets" Sessions when its actively being reconciliated (e.g. emit SSE event to show 'active tasks')

- [ ] Fix inconsistencies in frontend:
  - [ ]
    - [x] Fix Labs counter column in Workers' datatable (field mismatch: column read 'labs_count' but DTO sends 'cml_labs_count') — split into two columns: "CML Labs" (cml_labs_count, incl. untracked) and "Lab Records" (tracked LabRecords count from labRecords store)
  - [x] Fix Region column in Workers' datatable (field mismatch: column read 'region' but DTO sends 'aws_region')
  - [x] Fix Created column in workers' datatable: shows "time-ago" format (e.g. "2 hours ago") with full timestamp in native tooltip. Added `renderTimeAgo` utility to `dates.js`.
  - [x] Use icon-only buttons for all actions in all datatables: DataTable.ts core renders icon-only with label as tooltip, matching lcm-data-table pattern.
  - [x] Fix Workers' datatable component to show footer with pagination: now shows entry count when single page, full pagination controls when >1 page.

- [x] When a session is manually created from the frontend, the page now dynamically refreshes: lablet-modals.js emits `UI_SESSION_CREATED` event, SessionsPageV2 listens and reloads sessions from API. SSE `lablet.session.terminated` already triggers `removeSession` in store.

## Use Cases & UX

- [ ] Add use-cases to CPA:Sessions:
  - [ ] `Restart LabletSession` must terminate the current Session(s) (local, LDS, POD/Grading) and recreate a new one with timeslot starting (now(), unless future_timeslot selected). The original POD is probably still running, so just reassign it to the new session (`no Wipe`!)
  - [ ] `Reset POD and LabletSession` must wipe and restart the CML LabRecord in addition to `Restart LabletSession` (could be an option in confirmation dialog when `Restart Session`?)
  - [ ] `Available Workers` indicator showing the workers that are ready to accept new lablet session(s)
  - [ ] `Rename LabletSession`

- [x] Fix `Edit Lablet Definition`: the new resulting definition is marked `ready` directly while it MUST succeed "Sync" operation before moving to `ready`! (i.e. new content version must be ingested and made available to downstream dependencies!)
- [x] Fix LabletSession Details' modal ALWAYS opens, even when clicking an action button in the "Sessions" datatable' row — **Fixed**: Root cause was double-fire: row-click + session-title-link handler both opened modal. LcmDataTable guard now also excludes `[role="button"]` and `a[href]` from row-click, and session-title-link handler is the sole handler for definition name clicks.
- [ ] Limit the available Regions to `Create Lablet Session` modal
- [x] Fix Workers' nav-view's fleet capacity panel: was showing 0/0 due to key name mismatch in capacity derivation (all_cpu_count vs cpu_count). Fixed in UpdateWorkerCmlDataCommand + added DTO mapper fallback.
- [x] Fix Worker Name in AWS to show locally as the worker.name!
- [ ] Add support to detect the resource requirements from the cml.yml file (and any required supporting library - TBD) instead of having the user provide all details and in order to improve reliability, accuracy and relevancy (improving bottom-line' scheduling and placement decision).

Identify whether we need to pull any baseline

```lablet-definition
...
    # Resource requirements
    cpu_cores: int = 2
    memory_gb: int = 4
    storage_gb: int = 20
    nested_virt: bool = True
```


## Fix

- [ ] Port allocation detection from CML API: Extend PortAllocationService to detect ports already assigned to any CML Lab on any worker by querying the CML native API (lab definitions + external connectors). Track ports internally for both lablet-managed and locally-managed LabRecords. The CML API `/api/v0/labs/{lab_id}/external_connectors` should expose actual port mappings.
- [x] Auto-detect worker capacity: The derivation code already existed in UpdateWorkerCmlDataCommand but had a key name mismatch bug (reading `cpu_count` instead of `all_cpu_count` from the worker-controller's system_info dict). Fixed to try `all_`-prefixed keys first with unprefixed fallback. Also added DTO mapper fallback to derive capacity from CML system_info when `declared_capacity` is null. Workers will auto-populate capacity on next CML data refresh cycle.


## Features

- [ ] Manage Lablet Definitions (import directly from Mosaic and push to MinIO/S3)
- [x] Handle "LabRecord" separately from LabletInstance
- [ ] Add Resource Management for Lablet Operations (visible to admins only)
- [ ] Improve idle activity detection (CML websocket?)
- [ ] Add filter for users to see only instances for which a Tag matches the "USER_TAG_PATTERN" setting
- [ ] Manage user access to labs (sync user with CML users?)
- [ ] Expand on Monitoring


## Infrastructure


## Deployment

- [ ] Add Helm Chart deployment

## Development

- Expand Test coverage
- Consolidate ./notes vs ./docs
