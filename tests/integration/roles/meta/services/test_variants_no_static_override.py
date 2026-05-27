"""Integration guard: ``roles/<role>/meta/variants.yml`` MUST NOT
override a ``services.<key>.enabled`` or ``services.<key>.shared`` value
when ``roles/<role>/meta/services.yml`` declares that same attribute as
a static literal.

Rationale
---------

The variant-merge -> ``lookup('config', ...)`` chain has a propagation
gap: when a variant overrides an attribute whose base value in
``meta/services.yml`` is a literal (``true`` / ``false`` / a string
without Jinja), the merged value does not reliably reach downstream
consumers that read it via ``lookup('config', ...)``. The nextcloud
LDAP failure in CI run 25939428268 is the canonical example::

    # meta/services.yml
    ldap:
      enabled: true                                       # literal
      shared: "{{ 'svc-db-openldap' in group_names }}"

    # meta/variants.yml -- variant 1 disables LDAP entirely
    - services:
        ldap:
          enabled: false
          shared:  false

After merge the consumer SHOULD see ``services.ldap.enabled: false``;
in practice it sees the literal ``true`` from the base file, the
``user_ldap`` plugin runs anyway, and the LDAP bind fails because the
provider role was excluded from the round's inventory.

The fix is to remove the literal from the base file: make it dynamic
via the ``'<role>' in group_names`` shape, so the value is decided at
deploy time against the actual round inventory rather than via the
variant-merge step.

Required shape
--------------

For every first-level ``services.<key>.enabled`` or
``services.<key>.shared`` value that any variant in
``meta/variants.yml`` overrides, the base ``meta/services.yml`` value
MUST be either:

* dynamic (a Jinja expression -- typically
  ``"{{ '<role>' in group_names }}"``), OR
* absent (the variant introduces the flag and there is no base literal
  to silently win the merge).

Disallowed: a literal base value with a variant override of the same
first-level ``enabled`` / ``shared`` flag. The override may or may
not actually propagate. Nested attributes (``services.<key>.<sub>.enabled``,
``services.<key>.version``, custom plugin flags, …) are out of scope
here.

Exemption
---------

Place ``# nocheck: variants-static-override`` on the override line in
``meta/variants.yml`` when the divergence is intentional AND every
downstream consumer reads the merged value via a code path that is
provably immune to the propagation gap.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "variants-static-override"
_TRACKED_ATTRS = ("enabled", "shared")


def _is_static_literal(value) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and "{{" not in value and "{%" not in value


def _meta_lookup(meta_root, path):
    cur = meta_root
    for segment in path:
        if not isinstance(cur, dict) or segment not in cur:
            return False, None
        cur = cur[segment]
    return True, cur


def _variant_override_line_indices(variants_file):
    """Map ``(variant_index, override_path)`` -> 0-based line index for
    every leaf override under ``services.<key>...<attr>``.

    Parses the raw text rather than relying on YAML round-tripping so
    inline ``# nocheck:`` markers stay observable. Variant index is
    advanced at every top-level list item (lines that begin with
    ``- ``).
    """
    lines = read_text(str(variants_file)).splitlines()
    out = {}

    variant_index = -1
    stack: list[tuple[int, str]] = []

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if raw.startswith("- "):
            variant_index += 1
            stack = []
            after_dash = raw[2:]
            indent = 0
            line_for_key = after_dash
        else:
            indent = len(raw) - len(raw.lstrip(" "))
            line_for_key = stripped

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if ":" not in line_for_key:
            continue
        key = line_for_key.split(":", 1)[0].strip()
        if not key:
            continue

        stack.append((indent, key))

        value_part = line_for_key.split(":", 1)[1].strip()
        if not value_part or value_part.startswith("#"):
            continue

        # Only register leaves under services.<...>
        path_keys = [k for _, k in stack]
        if not path_keys or path_keys[0] != "services":
            continue
        sub_path = tuple(path_keys[1:])
        if not sub_path:
            continue
        out[(variant_index, sub_path)] = idx

    return out


class TestVariantsNoStaticOverride(unittest.TestCase):
    def test_variants_do_not_override_static_meta_attributes(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services_file = role_dir / ROLE_FILE_META_SERVICES
            variants_file = role_dir / ROLE_FILE_META_VARIANTS
            if not (services_file.is_file() and variants_file.is_file()):
                continue

            try:
                meta = load_yaml_any(services_file, default_if_missing={}) or {}
            except Exception as exc:
                offenders.append(f"{role_name}: meta/services.yml parse error: {exc}")
                continue
            try:
                variants = load_yaml_any(variants_file, default_if_missing=[]) or []
            except Exception as exc:
                offenders.append(f"{role_name}: meta/variants.yml parse error: {exc}")
                continue
            if not isinstance(variants, list) or not isinstance(meta, dict):
                continue

            line_indices = _variant_override_line_indices(variants_file)
            variants_text_lines = read_text(str(variants_file)).splitlines()

            for variant_index, variant in enumerate(variants):
                if not isinstance(variant, dict):
                    continue
                svc_overrides = variant.get("services") or {}
                if not isinstance(svc_overrides, dict):
                    continue

                stack = [([svc_key], attrs) for svc_key, attrs in svc_overrides.items()]
                while stack:
                    path, node = stack.pop()
                    if isinstance(node, dict):
                        for k, v in node.items():
                            stack.append(([*path, k], v))
                        continue

                    if len(path) != 2 or path[-1] not in _TRACKED_ATTRS:
                        continue

                    found, meta_value = _meta_lookup(meta, path)
                    if not found:
                        continue
                    if not _is_static_literal(meta_value):
                        continue

                    line_idx = line_indices.get((variant_index, tuple(path)))
                    if line_idx is not None and line_has_rule(
                        variants_text_lines[line_idx], _RULE
                    ):
                        continue

                    path_str = ".".join(["services", *path])
                    offenders.append(
                        f"{role_name}: variant[{variant_index}] overrides "
                        f"{path_str}={node!r} but meta/services.yml declares "
                        f"{path_str}={meta_value!r} as a static literal. "
                        f"Make the base value dynamic "
                        f"(\"{{{{ '<role>' in group_names }}}}\") or remove "
                        f"the variant override. Add `# nocheck: {_RULE}` on "
                        f"the override line for legitimate exceptions."
                    )

        if offenders:
            self.fail(
                f"meta/variants.yml overrides of static meta/services.yml values "
                f"({_RULE}, {len(offenders)} offender(s)):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
