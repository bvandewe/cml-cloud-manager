"""Read-only projection models in CPA.

Read models are write-once (or last-write-wins) projections owned by CPA but
populated from CloudEvents emitted by other services. They are *not*
aggregates; CPA never mutates them through commands except via projection
handlers (CQRS read side).
"""
