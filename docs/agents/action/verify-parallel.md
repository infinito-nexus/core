# Verify in two lanes at once 🛤️

Answer the branch's open questions from both ends at the same time: a CI run
that judges every row on clean runners, and a local loop that reproduces the
same roles on the stack you can actually inspect.

Neither lane alone closes a question. CI says whether a row comes up green on a
clean host but hands you a log hours later. The local stack answers in minutes
and lets you exec into the container, but it is one host with one slot and it
never proves the swarm path the way five distros do.

## What runs in parallel, and what must not

The two lanes run at the same time because they run on different machines. The
CI run is remote; the local loop is this host.

Inside the local lane nothing is parallel. `iteration/compose.md` requires
deploys to be serial, and a second deploy or a `make test` started next to a
running one is the SIGKILL that costs the whole round.

## 1. Dispatch the CI lane

Invoke the `i8-ci-trigger-priority` skill. It builds the priority line and
dispatches it; this lane does not re-derive candidates or axes of its own, so
that the two skills cannot drift apart on what a verification row is.

Keep two things from its report: the run URL, and the candidate table saying
what each pin rests on. The second one decides the local lane's scope.

Stop here if it refuses to dispatch. A refused line means a token cannot deploy
on this branch, and the local lane alone answers nothing about CI.

## 2. Arm the watch

```
/loop 30m /triage <run url>
```

30 minutes, because a deploy row takes 47 minutes in compose and 84 in swarm at
the median (`cli.administration.deploy.ci.timings`). A tick under fifteen
minutes mostly re-reads the same in-progress jobs; one over an hour lets a whole
chunk finish unnoticed.

**Never dispatch again while the watch is armed.** `entry-manual-steer.yml`
declares the branch's concurrency group with `cancel-in-progress`, so a second
dispatch cancels the run being triaged. The loop then triages a cancelled run
and reports every unfinished row as a failure, which is a phantom: those rows
never reached a verdict.

## 3. Run the local lane against what CI cannot settle for you

Take the roles in this order, and stop when the stack is busy rather than
queueing them:

1. **a fix that landed after the source run's verdict.** CI has never judged it;
   the local stack can, today.
2. **a pin that came from the pool default.** The CI row will be green or red
   for a combination nobody chose, so its verdict answers a different question
   than the one asked.
3. **a role whose failure was about container state** rather than placement:
   credentials, migrations, a healthcheck, a missing route. Those reproduce
   locally in full. Placement, overlay networking and replica counts do not.

Drive each one through [iteration/compose.md](iteration/compose.md) under the
`robot` skill. A role whose question is swarm-specific goes through
[iteration/swarm.md](iteration/swarm.md) instead; there is no point reproducing
an overlay problem in compose.

## 4. Let the lanes correct each other

The lanes disagree more often than they agree, and the disagreement is the
finding:

- **local green, CI red**: the failure is in the axis the local stack does not
  have. Read the CI artifact before touching the role.
- **local red, CI green**: usually local state the runner starts without, a
  stale image or a volume from an earlier iteration. Confirm before reporting a
  regression.
- **both red, different errors**: two causes, not one. Split them.

## 5. Close each question explicitly

A question is answered when its CI row is green **and** the local lane cleared
it, or when one lane was deliberately out of scope and the report says which.
Anything else is open, however green the run looks.
