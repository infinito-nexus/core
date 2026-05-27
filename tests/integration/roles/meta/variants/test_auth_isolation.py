"""Integration guard: an **auth-isolated** variant in
``roles/<role>/meta/variants.yml`` MUST explicitly disable every
non-auth service-key that any other variant of the same role declares.

Why
---

When a variant pins exactly one auth flavor (LDAP vs. OIDC/OAuth2)
the round under test exists to exercise that one auth path. Leaving
unrelated services (matomo, prometheus, dashboard, …) unset means
their effective value is decided by the deep-merge against
``meta/services.yml`` at deploy time — usually a dynamic
``"{{ '<role>' in group_names }}"`` expression — which makes the
resolver pull every matching provider role into the round's include
closure. The auth-only test scope balloons into a full integration
deploy, wasting CI minutes and obscuring the regression signal.

Pinning every non-auth flag to ``enabled: false, shared: false`` in
the auth-isolated variant keeps the closure tight: the resolver gets
a deterministic, minimal include set and the variant clearly states
"only this auth path, nothing else." The cost is a few explicit
``false`` lines per variant; the benefit is faster, more focused
matrix rounds.

Trigger
-------

A variant V is **auth-isolated** when:

1. EXACTLY ONE of the two auth flavors is set to ``enabled: true`` in
   V's ``services:`` block:

   * LDAP flavor: ``services.ldap.enabled: true``
   * OIDC/OAuth2 flavor: ``services.oidc.enabled: true`` OR
     ``services.oauth2.enabled: true``

2. AND no non-auth service-key in V's ``services:`` block has
   ``enabled: true``.

Variants that enable both auth flavors (a full integration test), or
neither (a no-auth baseline / teardown variant), or that pin auth
alongside other ``enabled: true`` services (a mixed integration test)
are NOT auth-isolated and this rule does not fire for them.

Obligation
----------

When V is auth-isolated, every service-key K that appears in any
variant of this role's ``meta/variants.yml`` AND is not in
``{ldap, oidc, oauth2}`` MUST be declared in V as
``enabled: false`` AND ``shared: false`` (literal).

Statically-enabled keys are exempt: when the role's
``meta/services.yml`` declares ``services.<K>.enabled`` as the YAML
literal ``true`` (i.e. not a Jinja expression), the dependency is
already a hard "always on" and pinning it ``false`` in V would only
break the role's own deploy without trimming any closure (the
resolver pulls the dep in regardless). Such keys MUST NOT be
declared in V at all — the inherited base value is correct.

Exemption
---------

Place ``# nocheck: variants-auth-isolation`` on the same line as the
variant's leading ``- services:`` (or on the line immediately above)
to skip the check for that single variant entry.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "variants-auth-isolation"
_AUTH = frozenset({"ldap", "oidc", "oauth2"})
_OIDC_GROUP = frozenset({"oidc", "oauth2"})
_LDAP_GROUP = frozenset({"ldap"})


def _is_enabled_true(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get("enabled") is True


def _auth_isolated(services: dict) -> bool:
    """A variant is auth-isolated when exactly one auth flavor is
    enabled=true in its services map AND no non-auth service-key is
    enabled=true. A variant that enables auth alongside non-auth
    services is a mixed integration test and falls outside this rule.
    """
    oidc_on = any(_is_enabled_true(services.get(k)) for k in _OIDC_GROUP)
    ldap_on = any(_is_enabled_true(services.get(k)) for k in _LDAP_GROUP)
    if oidc_on == ldap_on:
        return False
    for key, entry in services.items():
        if key in _AUTH:
            continue
        if _is_enabled_true(entry):
            return False
    return True


def _variant_header_line_numbers(variants_file: Path) -> dict[int, int]:
    """Map variant index (0-based) to the 1-based line number of its
    leading ``- services:`` (or ``- {}`` / ``- key:`` header).
    """
    lines = read_text(str(variants_file)).splitlines()
    out: dict[int, int] = {}
    variant_index = -1
    for idx, raw in enumerate(lines):
        if raw.startswith("- "):
            variant_index += 1
            out[variant_index] = idx + 1
    return out


def _is_literal_false(value: object) -> bool:
    return value is False


def _entry_pinned_false(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and _is_literal_false(entry.get("enabled"))
        and _is_literal_false(entry.get("shared"))
    )


def _statically_enabled_keys(services_file: Path) -> set[str]:
    try:
        services_raw = load_yaml_any(str(services_file), default_if_missing={})
    except Exception:
        return set()
    if not isinstance(services_raw, dict):
        return set()
    out: set[str] = set()
    for key, entry in services_raw.items():
        if (
            isinstance(key, str)
            and isinstance(entry, dict)
            and entry.get("enabled") is True
        ):
            out.add(key)
    return out


class TestVariantsAuthIsolation(unittest.TestCase):
    def test_auth_isolated_variants_explicitly_disable_non_auth_services(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            variants_file = role_dir / ROLE_FILE_META_VARIANTS
            if not variants_file.is_file():
                continue

            try:
                variants_raw = load_yaml_any(str(variants_file), default_if_missing=[])
            except Exception as exc:
                offenders.append(f"{role_name}: meta/variants.yml parse error: {exc}")
                continue
            if not isinstance(variants_raw, list):
                continue

            static_enabled = _statically_enabled_keys(
                role_dir / ROLE_FILE_META_SERVICES
            )

            non_auth_union: set[str] = set()
            for variant in variants_raw:
                if not isinstance(variant, dict):
                    continue
                services = variant.get("services") or {}
                if not isinstance(services, dict):
                    continue
                for key in services:
                    if (
                        isinstance(key, str)
                        and key not in _AUTH
                        and key not in static_enabled
                    ):
                        non_auth_union.add(key)

            header_lines = _variant_header_line_numbers(variants_file)
            text_lines = read_text(str(variants_file)).splitlines()

            for index, variant in enumerate(variants_raw):
                if not isinstance(variant, dict):
                    continue
                services = variant.get("services") or {}
                if not isinstance(services, dict):
                    continue
                if not _auth_isolated(services):
                    continue

                header_line = header_lines.get(index)
                if header_line is not None and is_suppressed_at(
                    text_lines, header_line, _RULE
                ):
                    continue

                missing = [
                    key
                    for key in sorted(non_auth_union)
                    if not _entry_pinned_false(services.get(key))
                ]

                if missing:
                    offenders.append(
                        f"{role_name}: variant[{index}] is auth-isolated "
                        f"but does not pin "
                        f"{', '.join(missing)} to "
                        f"`enabled: false, shared: false`. Either add the "
                        f"explicit false declarations or mark the variant "
                        f"with ``# nocheck: {_RULE}``."
                    )

        if offenders:
            self.fail(
                f"meta/variants.yml auth-isolated variants must pin every "
                f"non-auth service-key to literal false "
                f"({_RULE}, {len(offenders)} offender(s)):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
