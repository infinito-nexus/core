"""One-shot migration package for requirements 008 + 009 + 010.

Invoke from the repo root:

    python3 -m tasks.utils.migrate_meta_layout

Idempotent per role: re-running on an already-migrated tree is a no-op.
"""
