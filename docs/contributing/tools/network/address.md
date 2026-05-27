# `cli contributing network address suggest` 🌐

This page documents the contract of the `cli contributing network address suggest` helper and the rules contributors MUST follow when calling it.

Primary file:

- [__main__.py](../../../../cli/contributing/network/address/suggest/__main__.py)

## Purpose 🎯

`cli contributing network address suggest` proposes the next free per-role IPv4 subnet(s) based on the live role tree.
It walks every `roles/*/meta/server.yml`, collects occupied `networks.local.subnet` assignments, picks the smallest CIDR prefix that fits the requested client count, and proposes free sub-blocks gap-first then by increment within the established umbrella blocks.

## Inputs 🔧

| Flag                | Required | Default | Description                                                                                       |
|---------------------|:--------:|:-------:|---------------------------------------------------------------------------------------------------|
| `--clients N`       | yes      | n/a     | Minimum number of usable client IPs the role's subnet MUST hold.                                 |
| `--count K`         | no       | `1`     | How many free subnets to return.                                                                  |
| `--block <cidr>`    | no       | n/a     | Force suggestions inside a specific umbrella block (e.g. `--block 192.168.101.0/24`). Default is the union of currently used /24 umbrella blocks for the chosen prefix length. |

## Behaviour 🧮

1. Translate `--clients N` to the smallest CIDR prefix that fits (≤14 → `/28`, ≤30 → `/27`, ≤62 → `/26`, ≤126 → `/25`, ≤254 → `/24`, …).
2. Walk every `roles/*/meta/server.yml` and collect occupied CIDRs from `networks.local.subnet`.
3. Within each umbrella `/24` block already in use for the chosen prefix length: enumerate all sub-blocks of that prefix length, mark occupied vs. free.
4. __Gap-first:__ propose the lowest unoccupied sub-block.
5. __Increment fallback:__ if all sub-blocks of the active `/24` blocks are used, propose the next `/24` block in the established sequence (currently `192.168.101–105` for `/28`, `192.168.200–203` for `/24`).
6. __No established sequence:__ if the requested prefix size has no umbrella block established yet (e.g. `--clients 1000` → `/22` and no `/22` is in use), exit non-zero with a clear error suggesting that the operator pass `--block <cidr>` to bootstrap a new umbrella block manually.
7. For each suggestion, also print the __client capacity__ (`/28 → 14`, `/24 → 254`, …).

## Output 📤

- __stdout__ prints one subnet per line.
- __stderr__ prints per-suggestion capacity and a human-readable summary noting which umbrella block(s) were scanned.

## Examples 💡

Suggest two free `/28` subnets (14 clients each) inside the established umbrella blocks:

```bash
cli contributing network address suggest --clients 14 --count 2
```

Suggest one free `/24` subnet (254 clients) bootstrapped inside an explicit umbrella block:

```bash
cli contributing network address suggest --clients 254 --block 192.168.200.0/22
```

Suggest a single `/28` subnet (the default `--count 1`):

```bash
cli contributing network address suggest --clients 14
```

## Determinism 🧪

Given the same on-disk role layout and the same arguments, the helper produces identical output.
It exits non-zero with a clear error when the requested capacity cannot be satisfied within the configured umbrella block(s).

## Integration with `cli create role` 🧩

When `cli create role` scaffolds a new role, it prompts for `--clients N` and calls `cli contributing network address suggest --clients N --count 1` to fill in `meta/server.yml.networks.local.subnet` automatically.
The contributor MAY override the suggestion interactively.
See [port.md](port.md) for the matching ports flow.

## Related Pages 📚

- [port.md](port.md) is the sibling helper for host-bound ports.
- [layout.md](../../design/role/services/layout.md) describes the per-role `networks:` shape in `meta/server.yml`.
