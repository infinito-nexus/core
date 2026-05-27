"""Integration guard: every role whose `meta/services.yml` declares
`oidc` / `oauth2` OR `ldap` via the dynamic
``"{{ '<role>' in group_names }}"`` form MUST exercise the auth
matrix in `meta/variants.yml`.

Three coverage rules apply per role:

1. If `oidc` or `oauth2` is dynamic, `variants.yml` MUST contain at
   least one variant pinning that service to ``enabled: true`` AND
   ``shared: true`` together, and at least one pinning it to
   ``enabled: false`` AND ``shared: false`` together. Mixed-polarity
   pinning (e.g. ``enabled: true`` with ``shared: false``) does not
   count toward either side — the deploy modes the variants reflect
   are "auth fully present" vs. "auth fully absent".
2. The same rule applies to `ldap` whenever it is dynamic.
3. When both an auth service (`oidc` or `oauth2`) AND `ldap` are
   dynamic in the same role, at least one variant MUST pin the auth
   service to ``enabled: false`` WHILE pinning ``ldap.enabled: true``.
   That is the LDAP-only branch; without it, the matrix never
   exercises the LDAP authentication path in isolation from OIDC and
   the spec defaults to OIDC-only coverage by accident.

The check sits next to
[test_variants_coverage.py](./test_variants_coverage.py), which
enforces the broader "every dynamic flag needs both polarities"
contract per individual flag. This test layers the auth-specific
combinatorial requirement on top.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_AUTH_KEYS: tuple[str, ...] = ("oidc", "oauth2")
_LDAP_KEY: str = "ldap"

_MISSING = object()


def _is_dynamic_flag(value) -> bool:
    return isinstance(value, str) and "in group_names" in value


def _service_is_dynamic(services: dict, key: str) -> bool:
    entry = services.get(key)
    if not isinstance(entry, dict):
        return False
    return any(_is_dynamic_flag(entry.get(f)) for f in ("enabled", "shared"))


def _load_yaml(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return load_yaml_any(str(path), default_if_missing=None)
    except Exception:
        return None


def _variant_overrides_for(variant: dict, service_key: str, flag: str) -> object:
    services = variant.get("services") if isinstance(variant, dict) else None
    if not isinstance(services, dict):
        return _MISSING
    entry = services.get(service_key)
    if not isinstance(entry, dict):
        return _MISSING
    if flag not in entry:
        return _MISSING
    return entry[flag]


def _has_pair_polarity(variants: list[dict], service_key: str, polarity: bool) -> bool:
    """True iff some variant pins ``services.<key>.enabled`` AND
    ``services.<key>.shared`` to literal *polarity* in the same entry."""
    for variant in variants:
        e = _variant_overrides_for(variant, service_key, "enabled")
        s = _variant_overrides_for(variant, service_key, "shared")
        if e is polarity and s is polarity:
            return True
    return False


def _has_ldap_only_variant(variants: list[dict], auth_keys: list[str]) -> bool:
    """True iff some variant pins ``ldap.enabled: true`` while pinning
    every dynamic auth service (`oidc` / `oauth2`) to ``enabled:
    false`` in the SAME entry."""
    for variant in variants:
        if _variant_overrides_for(variant, _LDAP_KEY, "enabled") is not True:
            continue
        if all(
            _variant_overrides_for(variant, ak, "enabled") is False for ak in auth_keys
        ):
            return True
    return False


class TestAuthVariantsCoverage(unittest.TestCase):
    def test_oidc_oauth2_ldap_variants_cover_auth_matrix(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
            if not isinstance(services, dict):
                continue

            dynamic_auth = [k for k in _AUTH_KEYS if _service_is_dynamic(services, k)]
            ldap_dynamic = _service_is_dynamic(services, _LDAP_KEY)

            if not dynamic_auth and not ldap_dynamic:
                continue

            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants_raw = _load_yaml(variants_path)
            if not isinstance(variants_raw, list):
                offenders.append(
                    f"{role_name}: dynamic auth/ldap services in services.yml "
                    f"but {variants_path.relative_to(PROJECT_ROOT)} is missing "
                    f"or not a YAML list."
                )
                continue
            variants = [v if isinstance(v, dict) else {} for v in variants_raw]

            for ak in dynamic_auth:
                if not _has_pair_polarity(variants, ak, True):
                    offenders.append(
                        f"{role_name}: services.{ak} is dynamic but no variant "
                        f"pins ``services.{ak}.enabled: true`` AND "
                        f"``services.{ak}.shared: true`` together. Add a "
                        f"variant entry with both flags true."
                    )
                if not _has_pair_polarity(variants, ak, False):
                    offenders.append(
                        f"{role_name}: services.{ak} is dynamic but no variant "
                        f"pins ``services.{ak}.enabled: false`` AND "
                        f"``services.{ak}.shared: false`` together. Add a "
                        f"variant entry with both flags false."
                    )

            if ldap_dynamic:
                if not _has_pair_polarity(variants, _LDAP_KEY, True):
                    offenders.append(
                        f"{role_name}: services.ldap is dynamic but no variant "
                        f"pins ``services.ldap.enabled: true`` AND "
                        f"``services.ldap.shared: true`` together. Add a "
                        f"variant entry with both flags true."
                    )
                if not _has_pair_polarity(variants, _LDAP_KEY, False):
                    offenders.append(
                        f"{role_name}: services.ldap is dynamic but no variant "
                        f"pins ``services.ldap.enabled: false`` AND "
                        f"``services.ldap.shared: false`` together. Add a "
                        f"variant entry with both flags false."
                    )

            if (dynamic_auth and ldap_dynamic) and not _has_ldap_only_variant(
                variants, dynamic_auth
            ):
                auth_list = " / ".join(f"services.{k}" for k in dynamic_auth)
                offenders.append(
                    f"{role_name}: both ldap and {auth_list} are dynamic, "
                    f"but no variant pins ``ldap.enabled: true`` together "
                    f"with ``enabled: false`` on the auth service(s) — the "
                    f"LDAP-only branch is never exercised."
                )

        if offenders:
            self.fail(
                "Auth variant coverage is incomplete:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
