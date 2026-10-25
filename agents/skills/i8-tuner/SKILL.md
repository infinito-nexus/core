---
name: i8-tuner
description: >
  Find and apply performance optimizations in Infinito.Nexus without reducing
  logic, coverage or correctness: CI wall-clock, deploy duration, gate runtime
  and the translation pipeline. Every candidate is hardened with the
  `dialectic` skill before it is applied. Trigger on /i8-tuner, when a job dies
  on its time budget, when a gate grows slower, or when the operator asks where
  the time goes. Infinito.Nexus specific.
routines:
  - perf_sweep
---

# Performance Tuning

Follow the instructions from AGENTS.md, then work the loop below. One rule
outranks every optimization: **nothing that reduces logic, coverage or
correctness counts as a speed-up.**

## Forbidden, whatever it saves

- Dropping a spec, a play, a DR drill or a verification pass.
- Raising a timeout or a budget so a slow thing fits instead of getting faster.
- `failed_when: false`, retry-until-pass, a soft skip, a narrowed assertion.
- Trading a measured check for an unmeasured one.

A change that makes the clock smaller by testing less is reported to the
operator as a coverage cut for them to decide, never applied as a tuning.

## Measure first

Never tune what has not been measured. Sources, in order of authority:

| Question | Where it is answered |
| -------- | -------------------- |
| Which CI row burns its budget | `>>> Duration: distro=… took …s`, `budget=…s remaining=…s` and `rc=124` in the job log |
| Which target in a gate | the `📊 per-target wall-clock` table and the `FAILED TARGETS:` line |
| Which role in a deploy | the `role-runtimes-*` artifacts of the run |
| Which Ansible task | the play's own `--- 0.00s` recap at the end of the job log |
| Which engine a translation used | the `translated-by:` marks in `locale/*/LC_MESSAGES/*.po` |
| How long an engine takes per request class | the `took_ms` column of the svc-ai-s1 verdict history, averaged by `History.speed()` |
| What a variant is allowed to cost | the reservation and limit figures of `tests/integration/roles/meta/variants/test_resource_budget.py` against the 32/64 GB caps |
| What holds a GPU | `make compose-exec cmd='nvidia-smi --query-compute-apps=pid,used_memory --format=csv'` |

A `make` exit code is a lie here: judge a run by its wall-clock table, never by
`$?`. Stream every run to `/tmp/<slug>-<N>.log` and compare runs by their
tables rather than by re-running.

A number taken while another gate, deploy or translation run shared the machine
is invalid rather than merely noisy, and a comparison built from one is
discarded. Stop the competing job first, and take the before and the after
under the same conditions.

## Levers this repository has

- **Matrix shape**: jobs per chunk decides roles per job. Fewer roles per row
  shortens the row without taking a role out of the run.
- **Transport**: a Tor row pays SOCKS on every request. Compare a row against
  its clearnet twin before blaming the role.
- **Deploy mode**: `mode=update` wherever `reinstall` is not required.
- **Images**: a pinned digest skips a pull, a mirrored base skips a rate limit.
- **Translation**, wall-clock and throughput only: `INFINITO_I18N_LANES` and
  `INFINITO_I18N_BATCH_SIZE` in `.env`. This skill measures around the `i18n-*`
  targets and never runs them, never changes engine selection and never edits a
  prompt. Engine choice dominates throughput, because a specialized MT model on
  the GPU beats an LLM for bulk translation by a wide margin, so a dead engine
  is a performance defect and not only a gap — report that to the routine which
  owns those targets and settles quality against a per-language benchmark.
- **GPU**: a container reaches the card only with `NVIDIA_VISIBLE_DEVICES` set,
  since `runtime: nvidia` alone injects nothing. Compose only; swarm has no GPU
  path.
- **Thermals**: one package budget feeds CPU and iGPU. Loading the weak device
  takes power from the strong one, so "use every device" and "finish soonest"
  are different goals on this hardware.

## The loop

1. Measure, and name the single biggest cost with its line and its number.
2. Form one candidate optimization for it.
3. Harden it with the `dialectic` skill. The antithesis must try to show that
   the candidate removes coverage, hides a failure, or only moves the cost
   somewhere the measurement does not look.
4. Apply what survives, re-measure against the saved log of the previous run,
   and report the delta as a before and an after number.
5. Repeat until the next candidate is worth less than the run that measures it.

Begin by clarifying every open requirement with the `active-listening` skill,
then work under the `robot` skill. The task is finished when every applied
change carries a before and after number from the same measurement source, and
every rejected candidate is listed with the reason it fell.
