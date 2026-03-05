---
description: LCM Senior Architect implementation and verification pattern
---

This workflow applies the Senior Architect chain of thought. Use it whenever executing high-level architectural tasks or starting broad functional changes within Lablet Cloud Manager.

1. **Context Initialization**: Review Knowledge Item (KI) Summaries. Additionally review any relevant `notes/AD-*.md` decision files and `docs/` before drafting anything.
2. **Confirm Focus & Ambiguity Assessment**: Analyze the existing Reference Code patterns against the requirements. If context is unclear, stop and ask the user clarification questions. Do NOT assume design intent.
3. **Plan & Task Alignment**: Generate an `implementation_plan.md` using the task context and verify it aligns with the Clean Architecture rules. Map the plan steps into your `task.md` checklist items.
4. **Execution**: Proceed with code modifications keeping strictly to the bounded context rules (Domain → Application → API/UI → Integration → Infrastructure). Ensure test artifacts and UI bundlers (e.g., `make build-ui` and `make test`) are executed appropriately if modifying those layers.
5. **Knowledge Finalization**: Upon task completion and verification, update or append any learned gotchas, patterns, or new ADs (Architectural Decisions) to the `notes/` directory or the architecture documentation inside `docs/`.
