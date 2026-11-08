---
name: i8-variant-split
description: >
  Shorten an over-budget CI matrix row without losing coverage: split its
  primary role into new variants that together carry every edge, credit and
  axis pair the old row carried, verified against the repository's real round
  resolver, coverage credit, axes rotation and budget. Trigger when a row dies
  on the deploy cap, on /i8-variant-split, or when the operator asks to split a
  variant. Infinito.Nexus specific.
---

# Variant Split

Follow the instructions from AGENTS.md. A split is a **coverage change**: it is
always handed to the operator as an uncommitted proposal with its verification
table, never committed or merged by the agent.

## What must hold

A split replaces one row (`role#N`) with rows that share its work. Coverage is
judged over the **full job list**, every row of every sweep whether the budget
runs it or not: a tail past the budget is fine. The split keeps coverage only
when all of these hold, and each one is checked by
`python -m cli.meta.ci.variant_split`, never by eye:

| Check | Why a split can break it | Where it is checked |
| ----- | ------------------------ | ------------------- |
| Children | Every `role#variant` row must be deployed at that variant by some row of the job list, its own or the one that credits it | `compare`: job list `uncovered children`, `newly uncovered` |
| Edges | Every consumer-to-provider edge, including the dep-to-dep edges inside a closure and MCP pairs, must still run with the same active keys in some row of the job list, and at the same consumer and provider variants while the tree still declares them | `compare`: `edges lost over the job list` and `variant edges lost`; edges the split retires from a variant's own config are counted, not failed; `local`, `head` and `jobs` key counts are reported |
| No false credit | `_mark_covered` credits role-level closures and ignores pins, so a row can stay "covered" by a round that no longer deploys it at `#0`, that dictates its config, or by a coverer outside the job list | `compare`: `introduced false credits`, judged by row, coverer and reason; only one unchanged in all three is pre-existing |
| Pins | A `# variant-pin:` must reciprocate (`test_variant_pins`), settle (`test_variant_pin_fixed_point`) and never stand above a key its carrier switches off | `compare`: new pins, `unreciprocated`, new dark pins, new round errors |
| Limits | `MAX_VARIANTS` is 3 per role (`test_limit.py`) | `compare`: `variants grown` |
| Cost | A new row pays about 2.2 ks of fixed cost; per-app time is not linear | `cost` with measured per-app segments |

Head rows pushed past the budget and the mode, network and distro pairs that
rotate by position are reported per sweep 0-5 but do not fail the verdict. A
lost child, edge or true credit stays lost even when a check is noisy. Never
call a loss covered.

## Procedure

Stream every command to `/tmp/variant-split-<slug>-<N>.log` and read the log
rather than re-running it.

1. **Snapshot before.** On a tree whose `roles/` equals the merge target:
   `python -m cli.meta.ci.variant_split snapshot --seed <run id> --out /tmp/vs/before.json`.
   The seed is the id of the CI run the row failed in, as CI sets
   `INFINITO_DISCOVERY_SEED`; without it equal rows rank at random and the
   compare reports coverer moves that are noise. `compare` and `cost` refuse
   two snapshots of different seeds.
2. **Measure.** Turn the row's per-task wall TSVs (seconds, count, task
   header, one per pass) or its raw deploy log into per-app segments:
   `python -m cli.meta.ci.variant_split segments /tmp/vs/before.json --row <role#N> --runner <runner> --pass 1=<tsv> --pass 2=<tsv> [--cut 2] --out /tmp/vs/seg.json`.
   A cut pass makes every figure a lower bound; say so in the table. An app a
   pass never reached stays unpriced, never zero. To price apps the row does
   not deploy, measure another row on the **same runner** and join them with
   `python -m cli.meta.ci.variant_split merge /tmp/vs/seg.json /tmp/vs/seg-2.json --out /tmp/vs/seg-all.json`;
   `merge` refuses segments of two runners.
3. **Find the heavy core.** `python -m cli.meta.ci.variant_tree <role#N>`
   shows which dependency closure carries the weight and why each dependency
   runs the variant it runs.
4. **Edit** only `roles/<role>/meta/variants.yml`: new variants of the primary,
   each pinning only the sub-variants it needs, or turning keys off. Read the
   role's `AGENTS.md` first when it has one.
5. **Snapshot after** with the same `--seed` into `/tmp/vs/after.json`, then
   `python -m cli.meta.ci.variant_split compare /tmp/vs/before.json /tmp/vs/after.json --old <role#N> --split <role#N>,<role#M>`
   and `python -m cli.meta.ci.variant_split cost ... --segments /tmp/vs/seg.json`.
6. **Run the guards** that the edit touches:
   `tests/integration/roles/meta/variants`, `tests/lint/ansible/roles`,
   `tests/lint/agents` when present, `tests/lint/repository` and
   `tests/lint/filesystem`.
7. **Report** the verification table below, one line per replaced row.

## Pitfalls that already cost a round

- **Reciprocity blocks most pins.** A pin `partner#i` resolves only when the
  partner's `meta/services.yml` has a key gated on
  `'<carrier>' in group_names`, and exactly one partner variant sets that key
  literally true. A partner with no such back-reference cannot be pinned by
  that carrier. Adding the key is a role change and an operator decision.
- **The round index is a pin too.** A primary variant at index `i` runs every
  dependency with more than `i` variants at `#i`. A new variant therefore
  changes its dependencies' variants even without a marker, and the strict
  edge level shows it.
- **One closure can be the whole problem.** When the weight sits in one
  dependency's own closure, splitting the primary's keys only moves that
  closure into the new row. Report that instead of a split.
- **Edges against the job list, with the settled maps.** Compare against the
  rows of the job list, with the services maps the settled round uses, not the
  role's raw `meta/services.yml`.
- **A back-reference key joins the closures.** Coverage credits and the DNA
  clone election read the role-level closure, where a key gated on
  `group_names` always counts. A back-reference therefore puts carrier and
  partner in one cycle: every role embedding the partner then embeds the
  carrier, credits move to rows that never deploy it, and cycle members can
  share one DNA and drop out as clones. Snapshot again after adding one.
- **The partner's own row runs at the same index.** The partner variant a
  carrier pins also becomes a row of its own, whose round hands every other
  dependency that index. Its include can carry partners the carrier never
  pulls, and their pins can conflict with the one it needs.
- **A coverer's true credits fix its floor.** A row that truly covers
  `x#0` must keep deploying `x#0`, or the credit turns false. When those
  credits arrive through a shared dependency, that dependency's variant 0 must
  keep `x` too, and the floor of every row pulling it rises with it. Read the
  rows whose `covered_by` names the coverer in the snapshot before slimming the
  dependency.

## Operator decisions, never taken by the agent

- `# nocheck: variant-limit` or any other new nocheck marker or suppression:
  it needs the operator's approval for that role and variant, as the fourth
  `web-app-wordpress` variant had, and the marker names why the variant is
  needed.
- Back-reference keys in a dependency's `meta/services.yml`.
- A fix to `_mark_covered` for credits the pin-aware check proves false.
- Accepting any loss the verification table lists.

## Verification table

| Row | Job-list children uncovered (before/after) | Edges lost over the job list | Introduced false credits | Axes per sweep 0-5 (reported) | Pins and reciprocity | Saving per row | Net runner-time delta |
| --- | ------------------------------------------ | ---------------------------- | ------------------------ | ----------------------------- | -------------------- | -------------- | --------------------- |

Fill the axes column with the union over sweeps 0-5 and the per-sweep
maximum, and both time columns with their segment source and whether it is a
lower bound.

Begin by clarifying every open requirement with the `active-listening` skill
(escalating any design question you are not ~99% sure of to the `dialectic`
skill), then work under the `robot` skill. The task is finished when every row
the operator named has a filled table line, or a stated reason why no split
keeps its coverage together with the best candidate and exactly what it loses.
