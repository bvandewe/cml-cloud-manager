# AI Agent Guide

This guide provides comprehensive instructions for AI coding agents (GitHub Copilot, Cursor, Cline, etc.) working on the Lablet Cloud Manager codebase.

!!! info "Single Source of Truth"
    The content below is automatically included from `.github/copilot-instructions.md` - the single maintained source for AI agent instructions. Do not edit this page directly; instead, update the source file.

!!! tip "For Human Developers"
    While designed for AI agents, this guide is equally valuable for human developers new to the codebase. It covers essential architectural patterns, workflows, and conventions.

---

## AI Agent Instructions

--8<-- ".github/copilot-instructions.md"

---

## Using This Guide

### For AI Agents

This guide is automatically loaded by GitHub Copilot and other AI assistants that support `.github/copilot-instructions.md`. The instructions provide context for:

- Understanding the multi-SubApp architecture
- Following CQRS patterns with self-contained commands/queries
- Working with Neuroglia framework specifics
- Implementing authentication flows
- Managing background jobs and monitoring
- Maintaining code quality standards

### For Human Developers

Use this guide as:

- **Onboarding reference** for new team members
- **Quick reference** for architectural decisions
- **Convention checklist** before submitting PRs
- **Troubleshooting guide** for common issues

### Keeping Content Updated

When making architectural changes or adding new patterns:

1. Update `.github/copilot-instructions.md` (single source of truth)
2. This page will automatically reflect the changes
3. Update `CHANGELOG.md` if user-facing
4. Add detailed architectural decisions to `notes/*.md` if needed

## Related Documentation

- [Testing Guide](testing.md) - Comprehensive testing patterns and practices
- [Makefile Reference](makefile-reference.md) - All available development commands
- [Architecture Overview](../architecture/overview.md) - Deep dive into system design
- [Security](../security/authentication-flows.md) - Authentication and authorization details
- [Worker Monitoring](../architecture/worker-monitoring.md) - Background job orchestration
