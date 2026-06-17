# ADR-056: ADR Lifecycle & Supersession Conventions

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-13 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-016](./ADR-016-license-operations-via-worker-controller.md), [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md), [ADR-020](./ADR-020-session-entity-model.md), [ADR-021](./ADR-021-child-entity-architecture.md), [ADR-045](./ADR-045-multi-part-session-part-model.md), [ADR-054](./ADR-054-controller-topology-resource-kind.md) |

---

## 1. Context

The ADR log has grown to 50+ records spanning two architectural eras (the original single-`Lablet`
model and the generalized resource-plane). During consolidation we found three recurring problems:

1. **Header drift** — early ADRs use `## Status` / `## Date` headings or bullet lists; later ones
   use the attribute table. Tooling and the index cannot parse a single shape.
2. **Silent supersession** — newer ADRs (e.g. ADR-045, ADR-054) replace parts of older ones
   (ADR-020/021, ADR-016/017) without a machine-readable marker, so a reader of the old ADR has no
   forward pointer.
3. **Ambiguous status** — a cluster (ADR-044–054) sits at `Proposed` while the solution docs treat
   it as the north-star, with no convention for when `Proposed` becomes `Accepted`.

## 2. Decision

> **Stub.** Establishes the conventions; the index in
> [README.md](./README.md) is the canonical enforcement surface.

### 2.1 Mandatory header template

Every ADR MUST start with the attribute table (no `## Status` / bullet variants):

```markdown
| Attribute | Value |
|-----------|-------|
| **Status** | Proposed \| Accepted \| Accepted (Partially Superseded) \| Superseded \| Deprecated |
| **Date** | YYYY-MM-DD |
| **Deciders** | Architecture Team |
| **Related ADRs** | … |
```

### 2.2 Supersession markers (machine-readable)

When ADR-B replaces ADR-A in whole or part, **both** sides MUST carry a marker:

| On the newer ADR (B) | On the older ADR (A) |
|---|---|
| `Supersedes` / `Extends` row pointing to A | `Superseded by` / `Partially Superseded by` row pointing to B, and `Status` set to `Superseded` or `Accepted (Partially Superseded)` |

The index uses the notation `→ ADR-NNN` (superseded by) and `⊇ ADR-NNN` (supersedes) and renders
the supersession `flowchart` from these rows.

### 2.3 Status lifecycle

```
Proposed ──ratified──> Accepted ──partially replaced──> Accepted (Partially Superseded)
   │                       │                                      │
   └──rejected──> (deleted)└──fully replaced──> Superseded        └──fully replaced──> Superseded
```

- A `Proposed` cluster is ratified together (e.g. ADR-044–054) once the solution docs are signed
  off; the solution-doc status banner clears at the same time.
- `Deprecated` is reserved for decisions abandoned without a replacement.

### 2.4 Index obligations

Each new ADR MUST be added to **both** the [ADR index table](./README.md) (with its Supersession
column) **and** the `mkdocs.yml` nav in the same change.

## 3. Consequences

**Positive** — uniform, parseable headers; every superseded decision has a forward pointer; a clear
`Proposed → Accepted` ratification gate; the index and nav stay in lock-step.

**Negative / trade-offs** — a one-time pass to normalize legacy ADR headers (ADR-016/017/020/021
already done during consolidation); minor authoring overhead per new ADR.

## 4. Related

- [README.md](./README.md) — the ADR index, supersession graph, and template (enforcement surface).
- [ADR-054](./ADR-054-controller-topology-resource-kind.md) — first ADR to carry full supersession
  markers under this convention.
