# agents/scenarios/

One verification scenario per acceptance criterion that only a running stack
can prove: a probe, a refusal, a time bound or a restart. A lint or a unit test
proves everything that needs no stack; those criteria carry a `lint` or `unit`
proof in `agents/criteria.yml` instead of a scenario here.

## Format

Each scenario is `<id>.yml`:

```yaml
---
id: <id>
criterion: <criterion id from criteria.yml>
mode: compose | swarm | both
given: what the bundle has seeded
when: the action under test
then: the observable the scenario asserts
```

`make agents-verify scenario=<id>` runs one scenario against the already
running stack. The harness reads `then` as the pass condition; a human step is
played by the test personas `biber` and `mapache`.
