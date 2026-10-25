# Implementer

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in [`SOUL.md`](SOUL.md).

- Resume a sweep with the remaining apps only, in complexity order, from the last red app.
- Accept an operator override of a routine policy and record it in the run.
- Judge the gate by its table, never by the exit code.
- Do not retry a failure classified as deterministic.
