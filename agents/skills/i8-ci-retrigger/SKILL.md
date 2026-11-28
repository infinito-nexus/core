---
name: i8-ci-retrigger
description: >
  Retrigger the jobs a finished CI run did not pass: print them as one pasteable selection line, then push and trigger on the operator's pick. Infinito.Nexus specific.
routines: []
---

Follow the instructions from AGENTS.md, then retrigger exactly as this skill describes. Begin by clarifying every open requirement with the `kvb-think-listen` skill, then work under the `kvb-org-robot` skill. Never push and never dispatch yourself: both are the operator's, handed over as rows.

# Retrigger a run

A retrigger replays what a finished run already judged: each job that was not
green comes back as the selection it ran in, so the next run deploys those rows
first. Building a line from scratch for open questions is the
`i8-ci-trigger-priority` skill instead.

The run is the one the operator names (URL or id); none named: the latest
deploy run on the current branch. A bare id resolves against the current
branch's repository, so a run on another repository (a fork run) needs its URL.

## 1. Ask

One `AskUserQuestion` call with two questions, the first option of each the
recommended one:

| Question | Option | Flag |
|---|---|---|
| Which jobs? | every job not green, exact axes | none |
| | hard failures (❌) only, exact axes | `--strict` |
| | hard failures as role names, the rest exact | `--roles-only` |
| | every job not green as role names, axes to the rotation | `--any-axes` |
| What then? | push + trigger | |
| | only trigger | |
| | only print | |

## 2. Print the line

Run in the worktree of the run's branch, with the flag picked in step 1:

```bash
python -m cli.administration.deploy.ci.trigger --failed --run <run url> --print <flag>
```

stdout is one line of tokens separated by single spaces, sorted and
deduplicated exactly as the dispatch sends them, plus the priority entries the
run never deployed. Print it to the operator unchanged in one code block with
the token count beside it. `Nothing failed in that run; not triggering.` means
there is nothing to retrigger: report that and stop.

## 3. Hand over

Pushing is the operator's (AGENTS.md, Pushing) and `gh workflow run` is an
`ask` rule, so both go to the operator as rows of the `kvb-org-operator` skill:

```bash
operator.py add <slug>-push --dir <abs worktree> --command "<push command from AGENTS.md>" --reason "agents never push" --check pushed:<abs worktree>
operator.py add <slug>-trigger --dir <abs worktree> --command "python -m cli.administration.deploy.ci.trigger --failed --run <run url> <flag>" --reason "dispatch is an ask rule" --check manual
```

- **push + trigger**: both rows, the push first; the trigger dispatches the
  branch head, so it only verifies the fix once the push landed.
- **only trigger**: the trigger row alone.
- **only print**: no row.

The trigger row MUST carry the flag the print used, or it dispatches a
different line. The trigger refuses the whole run when a token cannot deploy
on the branch; report the token it names, never drop it to get the dispatch
through.
