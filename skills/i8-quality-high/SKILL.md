---
name: i8-quality-high
description: >
  Run the full quality gate (make quality-high: docs, autoformat, the whole test
  suite, then every lint target) in a loop until it is green end to end. Trigger
  on /i8-quality-high or when the operator asks for the high gate before a
  commit, a pull request, or a release. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then drive `make quality-high` to green.
It is `make quality` (docs, autoformat, test) followed by `make lint` — every
lint target, so budget around ten minutes per pass.

The fix loop and its forbidden shortcuts are the `test-fix` skill's; this skill
only pins the command and how to read its result.

## Running a pass

Run it in the background, streaming the full output to a log, and give the
operator the literal command to follow it:

    make quality-high 2>&1 | tee /tmp/make-quality-high-<N>.log
    tail -f /tmp/make-quality-high-<N>.log

Increment `<N>` per pass so runs stay comparable. Nothing else may run while it
does — no other test, script, or agent. The wall-clock budgets fail under
self-made load, and a stale `.ansible/.lock` from a parallel run breaks
ansible-lint silently.

## Reading the result

Judge by the two `📊 per-target wall-clock` tables (one for the test phase, one
for lint) and any `FAILED TARGETS:` line — never by the pipe exit code, which is
unreliable here. `docs` and `autoformat` write to the tree: run `git status`
after every pass and treat an unexpected diff as a finding, not as noise.

## Fixing

Every failure is fixed at its root. A lint hit is resolved by deleting the
offending construct, not by a `nocheck` marker, a loosened rule, or a target
dropped from the gate — any suppression needs the operator's explicit approval
and a stated reason.

Re-run the specific failing target first (`make test-unit`, `make lint-ansible`,
…), then the full `make quality-high` before declaring the gate green: a fix that
breaks a neighbouring target is not a fix.

## Working mode

Begin by clarifying every open requirement with the `active-listening` skill,
escalating any root-cause question you are not ~99% sure of to the `dialectic`
skill, then work under the `robot` skill until both phases pass clean. Report
calibrated confidence per the `confidence` skill. Do not commit unless the
operator asked for a commit.
