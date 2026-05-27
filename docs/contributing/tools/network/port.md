# `cli contributing network ports suggest` 🚪

This page documents the contract of the `cli contributing network ports suggest` helper and the rules contributors MUST follow when calling it.

Primary file:

- [__main__.py](../../../../cli/contributing/network/ports/suggest/__main__.py)

## Purpose 🎯

`cli contributing network ports suggest` proposes the next free host-bound port(s) inside a `PORT_BANDS.<scope>.<category>` band defined in [group_vars/all/08_networks.yml](../../../../group_vars/all/08_networks.yml).
It walks every `roles/*/meta/services.yml`, collects occupied `<entity>.ports.{local,public}.<category>` assignments across all roles and all entities, and proposes free slots gap-first then by increment.

`internal` ports are NOT supported by the suggester; they are dictated by upstream container images (`gitea=3000`, `postgres=5432`, …) and not allocated from a project-managed pool.
Internal ports are recorded in `services.<entity>.ports.internal.<category>` directly by the contributor.

## Inputs 🔧

| Flag                      | Required | Default | Description                                                                                       |
|---------------------------|:--------:|:-------:|---------------------------------------------------------------------------------------------------|
| `--scope local\|public`   | yes      | n/a     | Which scope to allocate from. `internal` is NOT a supported value.                                |
| `--category <name>`       | yes      | n/a     | Band category (`http`, `ssh`, `oauth2`, `relay`, …). Looked up in `PORT_BANDS.<scope>.<category>`. |
| `--count N`               | no       | `1`     | How many free ports (or relay ranges) to return.                                                  |
| `--range <start>-<end>`   | no       | n/a     | Override the band from `PORT_BANDS` for ad-hoc allocations.                                      |
| `--length N`              | yes for `relay` | n/a | Inclusive port count of the contiguous range. The produced span is `{start, end = start + N - 1}`. |

## Behaviour 🧮

### Single-port categories (everything except `relay`)

1. Read the band for `<scope>.<category>` from `PORT_BANDS`. If absent and no `--range` is given, exit non-zero with a clear error listing the available categories.
2. Walk every `roles/*/meta/services.yml` and collect ints under `<entity>.ports.<scope>.<category>` (across ALL entities and ALL roles).
3. __Gap-first:__ propose the lowest unoccupied port in the band.
4. __Increment fallback:__ if the band has no internal gaps, propose `max(used) + 1` (clamped to the band's upper bound).
5. Exit non-zero if the requested count cannot be satisfied within the band.

### Range category `relay`

1. Read the relay band from `PORT_BANDS.public.relay`.
2. Collect every `<entity>.ports.public.relay.{start,end}` pair as an occupied span.
3. __Gap-first:__ propose the lowest unoccupied contiguous span of size `--length N` within the band.
4. __Increment fallback:__ if no internal gap fits, propose `max(end) + 1` to `max(end) + N` (clamped to the band's upper bound).
5. Exit non-zero if `K` ranges of size `N` cannot be fit within the band.

## Output 📤

- __stdout__ prints a machine-readable list (one port per line for single-port categories, one `<start>-<end>` pair per line for `relay`).
- __stderr__ prints a human-readable summary noting which band was used and how many gaps were filled vs. appended.

## Examples 💡

Suggest three free localhost HTTP ports inside `PORT_BANDS.local.http`:

```bash
cli contributing network ports suggest --scope local --category http --count 3
```

Suggest one free public SSH port (`PORT_BANDS.public.ssh`):

```bash
cli contributing network ports suggest --scope public --category ssh --count 1
```

Suggest one free 10 000-port public relay range (`PORT_BANDS.public.relay`):

```bash
cli contributing network ports suggest --scope public --category relay --length 10000
```

Suggest five free oauth2-callback ports inside an explicit ad-hoc range:

```bash
cli contributing network ports suggest --scope local --category oauth2 --count 5 \
    --range 16500-16599
```

## Determinism 🧪

Given the same on-disk role layout and the same arguments, the helper produces identical output.
It exits non-zero with a clear error when the requested capacity cannot be satisfied within the configured band.

## Integration with `cli create role` 🧩

When `cli create role` scaffolds a new role, it prompts for required port categories per service entity and calls `cli contributing network ports suggest --scope <…> --category <…> --count 1` per slot to fill in the entity's `ports` map.
The contributor MAY override either suggestion interactively.
See [address.md](address.md) for the matching subnet flow.

## Related Pages 📚

- [address.md](address.md) is the sibling helper for subnets.
- [layout.md](../../design/role/services/layout.md) describes the per-entity `ports` shape.
