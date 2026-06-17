---
title: "Flow: Content Sync"
---

# Flow: Content Sync

> **Trigger:** an operator opens the CPA UI and clicks **Sync** on a Lablet (by name, e.g.
> `LAB-1.1.1`), or calls the equivalent API.

## Operator / Author summary

Syncing a Lablet **pulls the latest authored content from Mosaic and pushes it into the
platform** so it can be delivered. After a successful sync:

- CPA's **catalog entry** (`LabletDefinition`) is up to date.
- The content **bytes** live in internal blob storage (RustFS), which is what SE and LDS run
  from.
- **LDS** and **SE** have each refreshed their **own local view** of that content.

**What you need:** the content must be published in **Mosaic**, and its **form-qualified name**
must resolve via the environment-resolver. If sync fails at "resolve", it's a Mosaic/resolver
problem; if it fails at "fan-out", LDS or SE couldn't refresh.

**Sources of truth:** CPA trusts **Mosaic** (what content should exist); SE and LDS trust
**RustFS** (the bytes to run). Sync is the bridge.

---

## Architect detail

### Steps

1. **Resolve.** CPA (via lablet-controller) calls the **form-environment-resolver** with the
   form-qualified name → receives env vars including `MOSAIC_BASE_URL`.
2. **Download.** lablet-controller downloads the content **package (zip)** from the resolved
   Mosaic base URL.
3. **Store.** lablet-controller uploads the package to the **RustFS bucket** for that Lablet —
   the internal shared blob storage.
4. **Fan-out.** lablet-controller triggers **LDS** and **SE** to sync their own local views.
   Both treat RustFS as their source of truth.
5. **Record.** Result is recorded back on the `LabletDefinition` (synced version, timestamp,
   status) via `record_content_sync_result`.

### C4 — Component view (content sync)

```mermaid
C4Component
    title Component View — Content Sync

    Person(operator, "Operator")

    Container_Boundary(cpa, "control-plane-api") {
        Component(catalogctrl, "Catalog controller", "Neuroglia", "sync_lablet_definition")
        Component(catalogagg, "LabletDefinition", "Aggregate", "Catalog state + sync result")
    }
    Container_Boundary(lc, "lablet-controller") {
        Component(syncsvc, "ContentSyncService", "Hosted service", "Orchestrates the sync")
        Component(resolver, "EnvironmentResolverClient", "HTTP client", "form name -> MOSAIC_BASE_URL")
        Component(mosaicc, "MosaicClient", "HTTP client", "Downloads package zip")
        Component(s3c, "S3 client", "RustFS adapter", "Uploads package")
        Component(spi, "LDS / SE SPI", "HTTP clients", "Trigger downstream sync")
    }

    System_Ext(envres, "Form-Environment-Resolver", "name -> env vars")
    System_Ext(mosaic, "Mosaic", "Content SSOT")
    ContainerDb(blob, "RustFS / S3", "Object store", "Content bytes")
    System_Ext(lds, "LDS", "Student access")
    Container_Ext(se, "scenario-engine", "Automation engine")

    Rel(operator, catalogctrl, "Sync Lablet by name", "HTTPS")
    Rel(catalogctrl, syncsvc, "Start sync")
    Rel(syncsvc, resolver, "resolve(name)")
    Rel(resolver, envres, "GET env vars", "HTTP")
    Rel(syncsvc, mosaicc, "download(base_url)")
    Rel(mosaicc, mosaic, "GET package.zip", "HTTPS")
    Rel(syncsvc, s3c, "upload package")
    Rel(s3c, blob, "PUT", "S3")
    Rel(syncsvc, spi, "trigger sync")
    Rel(spi, lds, "POST sync", "HTTP")
    Rel(spi, se, "POST sync_content", "HTTP")
    Rel(se, blob, "Pull content", "S3")
    Rel(lds, blob, "Pull content", "S3")
    Rel(syncsvc, catalogagg, "record_content_sync_result")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

### Sequence

```mermaid
sequenceDiagram
    autonumber
    participant OP as Operator
    participant CPA as CPA (Catalog)
    participant LC as lablet-controller
    participant ER as Env-Resolver
    participant MO as Mosaic
    participant S3 as RustFS
    participant LDS as LDS
    participant SE as SE

    OP->>CPA: sync_lablet_definition(name)
    CPA->>LC: start content sync(name)
    LC->>ER: resolve(form_qualified_name)
    ER-->>LC: env vars (MOSAIC_BASE_URL, ...)
    LC->>MO: GET package.zip
    MO-->>LC: package bytes
    LC->>S3: PUT package -> lablet bucket
    S3-->>LC: ok
    par Fan-out
        LC->>LDS: trigger sync(bucket)
        LDS->>S3: pull content
        LDS-->>LC: synced
    and
        LC->>SE: sync_content(bucket)
        SE->>S3: pull content (PAv1)
        SE-->>LC: synced
    end
    LC->>CPA: record_content_sync_result(version, status)
    CPA-->>OP: sync complete
```

### Commands / queries / events

| Step | Actor | Operation | Kind |
|---|---|---|---|
| Trigger | CPA | `sync_lablet_definition` | Command |
| Resolve | lablet-controller → resolver | resolve by form-qualified name | HTTP query |
| Download | lablet-controller → Mosaic | GET package zip | HTTP |
| Store | lablet-controller → RustFS | PUT package | S3 |
| Fan-out | lablet-controller → LDS | trigger content sync | HTTP |
| Fan-out | lablet-controller → SE | `sync_content` | Command (HTTP) |
| Record | CPA | `record_content_sync_result` | Command |

### Failure handling

| Fails at | Symptom | Likely cause |
|---|---|---|
| Resolve | "cannot resolve content" | Form name not registered / resolver down |
| Download | "package not available" | Not published in Mosaic / wrong base URL |
| Store | "blob upload failed" | RustFS credentials / connectivity |
| Fan-out (LDS/SE) | catalog synced but delivery stale | Downstream service down — sync is **idempotent**, re-run safely |

Sync is **idempotent** and **re-runnable**: re-syncing overwrites the bucket and re-triggers
fan-out. No migration/backfill window is needed.
