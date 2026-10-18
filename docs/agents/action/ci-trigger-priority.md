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
- Every selection names every axis: role, variant, mode, onion state, distro
  and filesystem. Nothing is left to the rotation.

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

**Every token pins every axis.** `role#variant@mode+tor|clearnet%distro/filesystem`
carries all six, and none is left to the rotation. A run whose rows the
rotation is still free to move is not a verification run: the combination that
comes back is not the one the question was asked about, and a green row then
proves nothing about the red one it was supposed to answer.

The measurement decides **which** value each axis takes, never **whether** it
takes one:

| Axis | Pin the cheap value when | Pin the expensive value when |
|---|---|---|
| `mode` | the failure is not mode-specific | the row failed only in one mode, or the question is about swarm placement, overlay networking or replicas |
| `tor` | the onion is not involved | the failure mentions onion addresses, circuits or the tor proxy |
| `distro` | the failure is not package-manager specific | the question names a distro, or the row failed on exactly one |
| `filesystem` | the kind is deliverable, see the next step | the question is about the storage driver |

When `timings.fastest` returns `None`, the measurement has too few samples to
choose. That is not permission to leave the axis open; it moves the choice one
rung down:

1. the value the candidate's own failing row carried, read off the source run's
   job title. It reproduces the failure, which is the point of the line.
2. failing that, the only value the measurement saw at all, even below the
   sample minimum.
3. failing that, the run's pool default: `compose`, `clearnet`, `debian`,
   `btrfs`.

Say in the report which rung each pin came from. A pin from rung 3 is a guess
wearing a token, and the reader has to know that.

## 3. The filesystem is the one axis with a host condition

`scripts/tests/deploy/utils/filesystem/resolve.sh` serves a kind only when the
**host kernel** carries it: `zfs` needs `/dev/zfs` or a `modinfo zfs` hit, the
others need an entry in `/proc/filesystems` or a module. The distro images carry
only the userland (`scripts/install/filesystem.sh`).

A pool or token of exactly one kind is read as a human naming it, so the
applying step **fails the row instead of substituting** a kind the host can
serve. Pinning a kind the runner cannot deliver therefore produces a red job
that says nothing about the question.

The axis is still pinned; the condition decides **which kind**. Pick the kind
that satisfies both:

1. the measurement has samples of it, and
2. no fallback was reported for it. One deploy job log that was assigned the
   kind settles it: a delivered kind logs
   `docker-dataroot-filesystem: status=applied requested=<kind> effective=<kind>`,
   a substituted one logs a `fallback out of` note instead. Use the
   `ci-artifacts` skill to pull that one log rather than every log of the run.

No kind satisfies both, because the branch has no samples yet: pin `btrfs` and
say in the report that the pin rests on the pool default rather than on
evidence. Never drop the axis to avoid the question.

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
python -m cli.meta.ci.validate --priority "<tokens>" --modes auto --tor auto
```

`--modes auto --tor auto` at run level, because the tokens pin those axes per
row: a run-level pool of one would refuse every token that names the other
value, and a line that verifies a swarm question and a compose question at once
needs both open at run level and closed per token.

Then dispatch:

```bash
python -m cli.administration.deploy.ci.trigger \
  --priority "<tokens>" \
  --workspace false \
  --chunk-gate false
```

No `--mode`, `--tor`, `--distros` or `--filesystem`. Those inputs pin an axis
for the whole run, which the tokens already do per row, and a run-level pool
that disagrees with a token refuses it. The only reason to reach for them is a
line where every row genuinely shares one value, and even then the token form
is what the report has to show.

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

Every axis is pinned, so the report is not about what was left open. It is
about what each pin rests on: the measurement, the row's own failing
combination, or the pool default. A pin from the pool default is a guess, and a
green row under it answers a question nobody asked.

Name every question the run will **not** answer because a candidate was pinned
to one side of it. A line that verifies a fix in compose and says nothing about
swarm is a legitimate choice; a line that does that silently is not, because its
green result reads like a full answer.
