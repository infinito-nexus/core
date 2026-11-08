---
name: i8-variant-tree
description: >
  Print the variant tree one CI row really deploys, as text, JSON or YAML: the
  primary role#variant, every dependency with the variant its round settles on
  and why, each node's services and their state, the closure size and the
  axes the job list gives the row. Trigger on /i8-variant-tree or when the
  operator asks what a variant pulls in. Infinito.Nexus specific.
---

# Variant Tree

Follow the instructions from AGENTS.md, then run:

```bash
python -m cli.meta.ci.variant_tree <role#variant> [--json | --yaml] [--sweeps 0,1]
```

The tree reads the same resolver as `i8-variant-split`
(`cli.meta.ci.variant_split.rounds.settle`), so both always agree about what a
row deploys. It deploys and writes nothing.

| Field | Meaning |
| ----- | ------- |
| `primary` | The row, `role#variant`; a bare role means `#0`. A variant the role does not declare, or an unknown role, exits 2 naming the valid range. |
| `include_count` | The closure size as the `resolve_round` include count. The role-level model in `infinito meta roles applications complexity` is a different, larger number. |
| `nodes[].variant`, `reason` | The variant the round runs the node in: `primary`, `pin by <carrier>#<i>` (a `# variant-pin:` in force), `round index`, or `default 0` when the role has fewer variants than the round. |
| `nodes[].services[].state` | `required` (literal true in `meta/services.yml`), `presence-gated` (`'<role>' in group_names`), `forced by override` (a variant or a nested demand sets it true), `implicit` (no `enabled` flag), `templated`, or `off`; `deployed` says whether the provider is in the include. |
| `axes` | Per requested sweep: the mode, network, distro, filesystem and architecture `axes.assign` gives the row, its job-list position, whether it is inside the budget head, and its coverage credit. `--sweeps ''` skips this step, which runs the whole matrix pipeline. |

Report the tree the operator asked for in the format they named. When a row
errors (`VariantPinError`), report the error text; do not guess the tree.
