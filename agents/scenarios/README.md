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
requires:
  - <inventory path of a credential, e.g. API.anthropic.api_key>
steps:
  - run: <shell command run in the stack container>
    expect: <regular expression the output MUST contain>
    exit: <exit code the command MUST return, 0 when omitted>
```

`requires` and `steps` are optional. The harness in
[cli/agents/scenarios.py](../../cli/agents/scenarios.py) plays the steps in
order through the script behind `make compose-exec`; the first step that exits
otherwise or prints no match fails the scenario. A scenario without steps, or
one whose `requires` names an inventory credential that is not set, reports
`skipped`, never `passed`.

`make agents-verify` runs `call-test-agents-local.yml` through act, the same
file the CI runs. `make agents-verify scenario=<id>` replays one scenario
against the already running stack without act or a redeploy. A human step is
played by the test personas `biber` and `mapache`.
