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
  - a YAML mapping that mirrors the assembled application payload, so it can override anything reachable under `applications.<app>.{server,rbac,services,volumes,credentials}` (see [layout.md](../../../design/role/services/layout.md)).
- The literal `null` is normalised to `{}` so a bare `- ` list item stays valid.
- Scalars at entry level (numbers, strings, lists) are rejected.
- Variants are addressed by their **zero-based index** in the list.

## Entry Semantics 🧩

A **variant** is the role's assembled per-role meta payload (the same payload `applications.<app>` exposes; see [layout.md](../../../design/role/services/layout.md)) deep-merged with the matching list entry. The deep-merge follows the same rules as the [`applications`](../plugins/lookup/applications.md) lookup: dictionaries merge recursively, scalars and lists are replaced, and the entry has precedence.

- Entry `{}` produces the unchanged assembled payload.
- An entry with overrides produces a derived shape (for example WordPress Multisite domains).
- Variant 0 is the canonical baseline. The first entry SHOULD manually enumerate every dynamic service-key declared in `meta/services.yml` and pin each one to `enabled: true, shared: true`. The literal-true pins document the role's "all dynamics on" maximum-footprint deploy shape that every non-baseline variant either re-affirms or explicitly disables (see [test_non_baseline_explicit_disables.py](../../../../../tests/integration/roles/meta/variants/test_non_baseline_explicit_disables.py)).
- `{}` is permitted only when `meta/services.yml` declares no dynamic-enabled service-key, so there is nothing for the baseline to pin (for example pure matrix-driver roles such as `svc-bkp-volume-2-local`, whose every service-key originates in `variants.yml`).

## Credentials Interaction 🔐

A variant entry MAY toggle `services.<key>.enabled+shared` to pull additional shared providers into the round's closure (for example `services.ldap.enabled: true` to add `svc-db-openldap`).

The credential generator participates in this overlay so the providers a variant enables receive their schema-defined credentials in the inventory before deploy time.
See [Credentials Generation](../../../design/variants.md#credentials-generation-) in the design doc for the full CI/CD vs standalone flow and the involved CLI flags.

## Example 📝

```yaml
# roles/web-app-wordpress/meta/variants.yml

# variant 0: canonical Single-Site deploy with every dynamic flag on.
- services:
    dashboard:
      enabled: true
      shared: true
    matomo:
      enabled: true
      shared: true
    oauth2:
      enabled: true
      shared: true

# variant 1: Multisite deploy across blog/shop/news subdomains.
- server:
    domains:
      canonical:
        - "blog.{{ DOMAIN_PRIMARY }}"
        - "shop.{{ DOMAIN_PRIMARY }}"
        - "news.{{ DOMAIN_PRIMARY }}"
  services:
    dashboard:
      enabled: true
      shared: true
    matomo:
      enabled: true
      shared: true
    oauth2:
      enabled: true
      shared: true
    wordpress:
      multisite:
        enabled: true
```

This declares two variants. Variant 0 pins every dynamic service-key from `meta/services.yml` to `enabled: true, shared: true` so the maximum-footprint baseline is explicit. Variant 1 keeps the same dynamic flags on and additionally flips Multisite on against three canonical domains.

## Adding A Variant ➕

1. Edit `roles/<application_id>/meta/variants.yml` (create the file if absent).
2. Make sure variant 0 pins every dynamic service-key from `meta/services.yml` to `enabled: true, shared: true`.
3. Append a list entry for the new variant. For every dynamic service-key variant 0 enables, the new entry MUST either keep it on (re-pin `enabled: true, shared: true`) or explicitly disable it (`enabled: false, shared: false`). Add the variant-specific overrides that justify the new entry.
4. If the new variant relies on cleanup steps that the standard inter-round entity purge does not cover, extend the role's purge handling. The matrix wrapper invokes the standard purge between rounds for every app whose variant changed.
5. Add or extend the deep-merge edge-case tests in [test_variants.py](../../../../../tests/unit/utils/cache/test_variants.py) when the new variant exercises behaviour beyond the existing fixtures (for example list replacement vs. nested scalar override).

## What Not To Do 🚫

- You MUST NOT put per-environment overrides into `inventories/<env>/default.yml` for cases that belong to a single role; use this file instead. The environment inventory keeps only cross-cutting environment knobs.
- You MUST NOT introduce conditionals or templating tricks at the variant-list level. The deep-merge is straight YAML; complex shape decisions belong inside the role itself.
- You MUST NOT name the file `meta/inventory.yml` for any reason. See the placement rule.
