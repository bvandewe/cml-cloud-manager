# TODO


- [ ] Complete LifecyclePhase manager with PipelineExecutor and WorkflowExecutor (with synapse' serverless workflow syntax)
- [ ]

- [ ] Add use-cases to CPA:Sessions:
  - [ ] `Restart LabletSession` must terminate the current Session(s) (local, LDS, POD/Grading) and recreate a new one with timeslot starting (now(), unless future_timeslot selected). The original POD is probably still running, so just reassign it to the new session (`no Wipe`!)
  - [ ] `Reset POD and LabletSession` must wipe and restart the CML LabRecord in addition to `Restart LabletSession` (could be an option in confirmation dialog when `Restart Session`?)
  - [ ] `Available Workers` indicator showing the workers that are ready to accept new lablet session(s)
  - [ ] `Rename LabletSession`w

- [ ] Fix `Edit Lablet Definition`: the new resulting definition is marked `ready` directly while it MUST succeed "Sync" operation before moving to `ready`! (i.e. new content version must be ingested and made available to downstream dependencies!)
- [ ] Fix LabletSession Details' modal ALWAYS opens, even when clicking an action button in the "Sessions" datatable' row
- [ ] Limit the available Regions to `Create Lablet Session` modal
- [x] Fix Workers' nav-view's fleet capacity panel: its always showing 0/0 while workers are running
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
