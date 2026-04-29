# `meta/variants.yml` 🧬

Per-role matrix-deploy variant overrides. Each list entry declares one variant of the role's effective configuration; the development deploy CLI materialises one inventory folder per entry so every variant can be exercised against a real host.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../../../documentation.md).
For how the file is consumed at runtime (folder-per-round model, `--variant` / `--full-cycle`, cleanup behaviour), see [variants.md](../../../design/variants.md).

## Placement 📁

- The file MUST live at `roles/<application_id>/meta/variants.yml`.
- It MUST NOT be named `meta/inventory.yml`. The Ansible language server auto-applies the inventory schema to that filename, and the variant list does not satisfy it.
- A role MAY omit the file entirely. The loader then exposes exactly one variant equal to the assembled per-role meta payload (`meta/services.yml` + `meta/server.yml` + `meta/rbac.yml` + `meta/volumes.yml` + `apply_schema()`'d `meta/schema.yml`) unchanged.

## File Format 📋

- The top-level node MUST be a YAML list. A non-list root is a hard error.
- Each list entry MUST be either:
  - the empty mapping `{}` (the canonical no-override entry), or
  - a YAML mapping that mirrors the assembled application payload — i.e. it can override anything reachable under `applications.<app>.{server,rbac,services,volumes,credentials}` (see [layout.md](../../../design/services/layout.md)).
- The literal `null` is normalised to `{}` so a bare `- ` list item stays valid.
- Scalars at entry level (numbers, strings, lists) are rejected.
- Variants are addressed by their **zero-based index** in the list.

## Entry Semantics 🧩

A **variant** is the role's assembled per-role meta payload (the same payload `applications.<app>` exposes — see [layout.md](../../../design/services/layout.md)) deep-merged with the matching list entry. The deep-merge follows the same rules as the [`applications`](../plugins/lookup/applications.md) lookup: dictionaries merge recursively, scalars and lists are replaced, and the entry has precedence.

- Entry `{}` produces the unchanged assembled payload, which becomes variant 0.
- An entry with overrides produces a derived shape (for example WordPress Multisite domains).
- Variant 0 is the canonical baseline. The first entry SHOULD therefore be `{}` whenever the role has a meaningful "default deploy" shape, so consumers reading variant 0 keep getting the historical payload unchanged.

## Example 📝

```yaml
# roles/web-app-wordpress/meta/variants.yml

# variant 0: canonical Single-Site deploy.
- {}

# variant 1: Multisite deploy across blog/shop/news subdomains.
- server:
    domains:
      canonical:
        - "blog.{{ DOMAIN_PRIMARY }}"
        - "shop.{{ DOMAIN_PRIMARY }}"
        - "news.{{ DOMAIN_PRIMARY }}"
  services:
    wordpress:
      multisite:
        enabled: true
```

This declares two variants. Variant 0 is the baseline; variant 1 flips Multisite on against three canonical domains.

## Adding A Variant ➕

1. Edit `roles/<application_id>/meta/variants.yml` (create the file if absent).
2. Append a list entry containing only the keys that differ from variant 0.
3. If the new variant relies on cleanup steps that the standard inter-round entity purge does not cover, extend the role's purge handling. The matrix wrapper invokes the standard purge between rounds for every app whose variant changed.
4. Add or extend the deep-merge edge-case tests in [test_variants.py](../../../../../tests/unit/utils/cache/test_variants.py) when the new variant exercises behaviour beyond the existing fixtures (for example list replacement vs. nested scalar override).

## What Not To Do 🚫

- You MUST NOT put per-environment overrides into `inventories/<env>/default.yml` for cases that belong to a single role; use this file instead. The environment inventory keeps only cross-cutting environment knobs.
- You MUST NOT introduce conditionals or templating tricks at the variant-list level. The deep-merge is straight YAML; complex shape decisions belong inside the role itself.
- You MUST NOT rename the file back to `meta/inventory.yml` for any reason. See the placement rule.
