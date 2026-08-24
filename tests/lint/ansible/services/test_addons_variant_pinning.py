"""Lint: variant 1 decides every statically-on addon, and never a dynamic one.

An addon's ``enabled`` in ``meta/addons/<id>.yml`` is either

* **static** -- a literal boolean, the same in every deploy, or
* **dynamic** -- a Jinja expression that resolves per deploy against a service
  flag, an API credential, the SSO plugin choice or ``group_names``.

A dynamic addon already follows its variant: switch the service off and the
expression yields false. A statically-on addon does not. It installs in every
variant, so each non-baseline round pays for plugins it does not exercise, and
variant 0 stops being the only maximum-footprint shape -- the property
``meta/variants.yml`` exists to document.

Variant 1 is where that decision lives, and the later variants reference it
with a YAML alias, so the set has one spot::

    # variant 1
      addons: &addons_static_off
        calendar:
          enabled: false
        ...
    # variant 2
      addons: *addons_static_off

Rules
-----

For every role that ships ``meta/addons/`` and declares **more than one**
variant in ``meta/variants.yml``:

1. Every addon whose base ``enabled`` is the literal ``true`` MUST appear in
   variant 1's ``addons`` map with ``enabled: false``. A base of literal
   ``false`` is out of scope: the pin would override nothing.
2. No addon whose base ``enabled`` is a Jinja expression may be pinned in ANY
   variant. Pinning one replaces the expression with a constant and silently
   decouples the addon from the service it was written to follow.
3. Every later variant MUST carry the same set with the same value -- in
   practice by aliasing variant 1's anchor. A variant that omits one lets
   deep-merge fall back to variant 0's literal ``true`` and the addon returns
   unannounced. Variant-specific pins beyond that set stay allowed, so a
   variant may still switch a statically-off addon on.

A role with a single variant is out of scope entirely -- there is no
non-baseline round to trim.

Per-addon opt-out: ``# nocheck: addons-variant-pinning`` in the head of
``meta/addons/<id>.yml``, with the reason the addon must install everywhere.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_VARIANTS
from utils.update.addons import iter_addon_files

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "addons-variant-pinning"


def _base_enabled(addon_file: Path):
    """Return the addon's declared ``enabled`` value, or None when absent.

    Args:
        addon_file: path of a ``meta/addons/<id>.yml``.
    """
    spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
    if not isinstance(spec, Mapping):
        return None
    return spec.get("enabled")


def _variants(role_dir: Path) -> list:
    """Return the role's variant list, empty when the file is absent.

    Args:
        role_dir: the ``roles/<role>`` directory.
    """
    data = load_yaml_any(str(role_dir / ROLE_FILE_META_VARIANTS), default_if_missing=[])
    return data if isinstance(data, list) else []


def _pinned_addons(variant) -> Mapping:
    """Return a variant entry's ``addons`` map, empty when it declares none.

    Args:
        variant: one entry of the variant list.
    """
    if not isinstance(variant, Mapping):
        return {}
    addons = variant.get("addons")
    return addons if isinstance(addons, Mapping) else {}


class TestAddonsVariantPinning(unittest.TestCase):
    def _roles(self) -> dict:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")
        by_role: dict = {}
        for role, addon_file in iter_addon_files(roles_root):
            if is_suppressed_in_head(read_text(str(addon_file)).splitlines(), _RULE):
                continue
            by_role.setdefault(role, []).append(addon_file)
        return by_role

    def test_statically_enabled_addons_are_disabled_in_variant_1(self) -> None:
        findings: list[str] = []
        for role, addon_files in sorted(self._roles().items()):
            role_dir = PROJECT_ROOT / "roles" / role
            variants = _variants(role_dir)
            if len(variants) < 2:
                continue
            pinned = _pinned_addons(variants[1])
            for addon_file in addon_files:
                if _base_enabled(addon_file) is not True:
                    continue
                addon_id = addon_file.stem
                entry = pinned.get(addon_id)
                value = entry.get("enabled") if isinstance(entry, Mapping) else None
                if value is False:
                    continue
                findings.append(
                    f"- {role}/{ROLE_DIR_META_ADDONS}/{addon_id}.yml is statically "
                    f"enabled but variant 1 pins {value!r}"
                )

        if not findings:
            return

        self.fail(
            "A statically-enabled addon installs in every variant, so each "
            "non-baseline round pays for a plugin it does not exercise. Pin it "
            "off in variant 1 and alias that map from the later variants:\n\n"
            "      addons: &addons_static_off\n"
            "        <addon_id>:\n"
            "          enabled: false\n\n" + "\n".join(findings) + "\n\n"
            f"Per-addon opt-out: `# nocheck: {_RULE}` with a reason."
        )

    def test_later_variants_carry_variant_1s_disabled_set(self) -> None:
        findings: list[str] = []
        for role, addon_files in sorted(self._roles().items()):
            role_dir = PROJECT_ROOT / "roles" / role
            variants = _variants(role_dir)
            if len(variants) < 3:
                continue
            required = sorted(f.stem for f in addon_files if _base_enabled(f) is True)
            for index in range(2, len(variants)):
                pinned = _pinned_addons(variants[index])
                for addon_id in required:
                    entry = pinned.get(addon_id)
                    value = entry.get("enabled") if isinstance(entry, Mapping) else None
                    if value is False:
                        continue
                    findings.append(
                        f"- {role}/{ROLE_FILE_META_VARIANTS}: variant {index} pins "
                        f"{addon_id!r} as {value!r}, variant 1 disables it"
                    )

        if not findings:
            return

        self.fail(
            "Variant 1 owns the disabled-addon set; a later variant that omits an "
            "entry lets deep-merge fall back to variant 0's literal true and the "
            "addon installs again. Reference the set instead of restating it:\n\n"
            "    # variant 1\n"
            "      addons: &addons_static_off\n"
            "        <addon_id>:\n"
            "          enabled: false\n"
            "    # variant 2 and later\n"
            "      addons: *addons_static_off\n\n" + "\n".join(findings) + "\n\n"
            f"Per-addon opt-out: `# nocheck: {_RULE}` with a reason."
        )

    def test_dynamic_addons_are_never_pinned_in_a_variant(self) -> None:
        findings: list[str] = []
        for role, addon_files in sorted(self._roles().items()):
            role_dir = PROJECT_ROOT / "roles" / role
            variants = _variants(role_dir)
            if len(variants) < 2:
                continue
            dynamic = {f.stem for f in addon_files if isinstance(_base_enabled(f), str)}
            for index, variant in enumerate(variants):
                findings.extend(
                    f"- {role}/{ROLE_FILE_META_VARIANTS}: variant {index} pins "
                    f"dynamic addon {addon_id!r}"
                    for addon_id in sorted(dynamic & set(_pinned_addons(variant)))
                )

        if not findings:
            return

        self.fail(
            "A dynamic addon resolves its own enablement per deploy. Pinning it "
            "in a variant replaces that expression with a constant and decouples "
            "the addon from the service it follows -- switch the service instead:"
            "\n\n" + "\n".join(findings) + "\n\n"
            f"Per-addon opt-out: `# nocheck: {_RULE}` with a reason."
        )


if __name__ == "__main__":
    unittest.main()
