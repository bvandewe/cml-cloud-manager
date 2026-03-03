# Technical Constraints

This folder documents known technical constraints, limitations, and design trade-offs in the Lablet Cloud Manager system. These constraints are important for understanding system behavior and planning future improvements.

## Index

| Constraint | Component | Severity | Status |
|------------|-----------|----------|--------|
| [CONST-001](CONST-001-port-allocation-race-condition.md) | Port Allocation | Medium | Known |

## Constraint Document Template

Each constraint document should follow this structure:

```markdown
# CONST-XXX: Title

| Attribute | Value |
|-----------|-------|
| **ID** | CONST-XXX |
| **Component** | Affected component(s) |
| **Severity** | Low / Medium / High / Critical |
| **Status** | Known / Mitigated / Resolved |
| **Created** | YYYY-MM-DD |
| **Updated** | YYYY-MM-DD |

## Description
Brief description of the constraint.

## Impact
What functionality is affected and how.

## Root Cause
Why this constraint exists.

## Current Behavior
How the system behaves with this constraint.

## Workaround / Mitigation
Any current workarounds in place.

## Resolution Path
How this could be fixed in the future.

## Related
- Links to related ADRs, issues, or code
```

## Severity Levels

- **Critical**: System cannot function correctly; data loss or corruption possible
- **High**: Major feature limitation; workaround required for normal operation
- **Medium**: Feature works but with known edge cases; workaround available
- **Low**: Minor inconvenience; cosmetic or rarely encountered
