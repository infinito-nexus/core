# Lead a CI run with a priority line 🔎

Turn the questions a branch still has open into the priority line of one manual
CI run, so it answers as many of them as possible in the cheapest combination
that still counts as an answer.

The run this builds differs from a retrigger: a retrigger replays what a run
already judged, this one asks about rows nobody has judged yet or whose verdict
is still disputed. It therefore states its axes instead of carrying them over.

## Scope

- At most 20 selections on the priority line. The bound is the point: a
  priority line long enough to fill the whole queue window stops being a
  priority.
- `workspace=false` and `chunk_gate=false`.
- Every selection names role, variant, mode and onion state; distro and
  filesystem are named only under the conditions below.

## 1. Collect the candidates

Two sources, run verdicts first:

1. The selections of the last finished deploy run on the branch that are not
   green. `cli.administration.deploy.ci.selections.failed_selections` reads
   them straight out of the job titles, so each candidate arrives with the
   variant, mode and onion state it failed in.
2. The root causes that are still open without a run to point at: a fix landed
   whose effect nobody has seen, or a diagnosis that was never confirmed
   against the deployed code.

Take source 1 in full, then fill up to 20 from source 2. A row that source 1
already covers is not added twice.

Stop and say so when the two sources together yield fewer than three
candidates. A run that verifies two rows is cheaper to ask for by name.

## 2. Measure the axes before choosing them

```bash
python -m cli.administration.deploy.ci.timings --runs 6
```

It reports the median wall-clock per axis value off the finished runs of the
branch, with the sample count behind each one. Measured on this repository, the
spread is not marginal: `swarm` costs roughly twice what `compose` costs, and
an onion row roughly a third more than a clearnet one.

Choose per axis, and choose the cheap value **only where the axis is not part
of the question**:

| Axis | Pin the cheap value when | Keep the expensive value when |
|---|---|---|
| `mode` | the failure is not mode-specific | the row failed only in one mode, or the question is about swarm placement, overlay networking or replicas |
| `tor` | the onion is not involved | the failure mentions onion addresses, circuits or the tor proxy |
| `distro` | the failure is not package-manager specific | the question names a distro, or the row failed on exactly one |
| `filesystem` | see the condition below | always, otherwise |

An axis with no value that reached the minimum sample count stays unpinned.
`timings.fastest` returns `None` there, and that is an answer: the measurement
cannot carry the pin, so the rotation keeps the axis.

## 3. The filesystem is the one axis with a host condition

`scripts/tests/deploy/utils/filesystem/resolve.sh` serves a kind only when the
**host kernel** carries it: `zfs` needs `/dev/zfs` or a `modinfo zfs` hit, the
others need an entry in `/proc/filesystems` or a module. The distro images carry
only the userland (`scripts/install/filesystem.sh`).

A pool or token of exactly one kind is read as a human naming it, so the
applying step **fails the row instead of substituting** a kind the host can
serve. Pinning a kind the runner cannot deliver therefore produces a red job
that says nothing about the question.

Pin the filesystem only when both hold:

1. the measurement has enough samples of that kind, and
2. no fallback was reported for it. A fallback is always logged as
   `filesystem: ... fallback out of ...`, so one deploy job log that was
   assigned the kind settles it. Use the `ci-artifacts` skill to pull that one
   log rather than every log of the run.

Otherwise leave `filesystem` out of the tokens and out of the run input.

## 4. Validate, then dispatch

The trigger validates on its own before it dispatches, and refuses the whole
run when a token cannot deploy on this branch. That refusal is not about deploy
minutes: `call-orchestrator.yml` runs the same check as its first job and every
other job needs it, so a bad token never reaches a chunk. It reaches the
branch's concurrency group, which `entry-manual-steer.yml` declares with
`cancel-in-progress`, so the doomed dispatch cancels the run currently in flight
before failing its own validation.

Check it first anyway when building the line by hand, because the same check
outside the trigger costs a second and names every problem at once:

```bash
python -m cli.meta.ci.validate --priority "<tokens>" --modes <mode> --tor <tor>
```

Then dispatch:

```bash
python -m cli.administration.deploy.ci.trigger \
  --priority "<tokens>" \
  --workspace false \
  --chunk-gate false
```

Add `--mode`, `--tor`, `--distros` or `--filesystem` only for an axis that step
2 settled for the whole run rather than per token.

A refusal names the token and why. Fix the token, never the check: a variant
that no longer exists means the list was carried over from an older run, and
dropping the pin only moves the wrong row into the queue.

A warning does not refuse, and it carries two very different meanings. Tell
them apart before ignoring it:

- **the role id is wrong.** Candidates assembled from memory or from a
  conversation get prefixes wrong: `web-svc-openresty` warns, `svc-prx-openresty`
  resolves. Check `roles/` for the id before dropping the candidate.
- **the role is outside the envelope.** `web-app-minio` warns whatever is
  pinned, because its `lifecycle` is `eol`. That candidate does not belong on a
  verification line at all; no run will judge it.

## 5. Report what the run can and cannot answer

Say per candidate which axis was pinned and which was left to the rotation, and
name every question the run will **not** answer because its axis was too
expensive to include. A cheap run that silently drops the swarm half of a
question is worse than an expensive one, because its green result reads like an
answer.
