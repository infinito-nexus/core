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

A role with a single variant is out of scope of rules 1 to 3 -- there is no
non-baseline round to trim.

4. Every optional addon (``required`` not ``true``) MUST take both states
   across the role's variants, so the CI matrix exercises it on and off: a
   static addon needs a variant resolving it ``true`` and one resolving it
   ``false``, a dynamic addon needs a second variant to switch its service
   in. A role without ``meta/variants.yml`` deploys one round. Rule 4 is
   warn-only until every listed addon has a proving round: it emits one
   GitHub Actions warning per unexercised addon and never fails.

Per-addon opt-out: ``# nocheck: addons-variant-pinning`` in the head of
``meta/addons/<id>.yml``, with the reason the addon must install everywhere
or can never be switched on in CI.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.message import warning as gha_warning
from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_VARIANTS
from utils.update.addons import iter_addon_files

from . import PROJECT_ROOT

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


def _pinned_enabled(variant, addon_id: str):
    """
    Args:
        variant: one entry of the variant list.
        addon_id: the addon to look up.

    Returns:
        The ``enabled`` value the variant pins for *addon_id*, None when it
        pins none.
    """
    entry = _pinned_addons(variant).get(addon_id)
    return entry.get("enabled") if isinstance(entry, Mapping) else None


def _addons_line_reason(lines: list[str]) -> str | None:
    """
    Args:
        lines: the lines of one variant entry, its ``- `` line first.

    Returns:
        The reason the marker on the entry's own ``addons:`` line states,
        empty when it states none, None when that line carries no marker.
    """
    from utils.annotations.suppress import marker_reason

    own = next(
        (
            line
            for line in lines
            if line[:2] in ("- ", "  ") and line[2:].startswith("addons:")
        ),
        None,
    )
    return None if own is None else marker_reason(own, _RULE)


def _addon_carriers(
    text: str, variants: list, required: list[str]
) -> tuple[set[int], list[str]]:
    """
    Args:
        text: the role's ``meta/variants.yml``.
        variants: the parsed variant list of that file.
        required: the ids of the role's statically enabled addons.

    Returns:
        The indices of the variants whose own ``addons:`` line carries
        ``# nocheck: addons-variant-pinning``, and one finding per marker on
        variant 0 or 1, per reason shorter than ``MIN_REASON_CHARS``, per
        carrier while variant 0 still installs the static addons, per carrier
        that leaves none of them on, and for more than one marked variant.
    """
    from cli.administration.inventory.validate.open_subtrees import (
        MIN_REASON_CHARS,
    )

    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith("- ")]
    baseline_off = all(
        _pinned_enabled(variants[0] if variants else {}, a) is False for a in required
    )
    carriers: set[int] = set()
    findings: list[str] = []
    for index, (start, end) in enumerate(
        zip(starts, [*starts[1:], len(lines)], strict=True)
    ):
        reason = _addons_line_reason(lines[start:end])
        if reason is None:
            continue
        carriers.add(index)
        variant = variants[index] if index < len(variants) else {}
        if index < 2:
            findings.append(
                f"variant {index} carries the marker, but variant 1 owns the "
                "static-off set"
            )
        if len(reason) < MIN_REASON_CHARS:
            findings.append(
                f"variant {index} carries the marker without a reason of at "
                f"least {MIN_REASON_CHARS} characters"
            )
        if not baseline_off:
            findings.append(
                f"variant {index} carries the marker, but v0 already carries the "
                "static addons"
            )
        if all(_pinned_enabled(variant, a) is False for a in required):
            findings.append(
                f"variant {index}: carrier marker on a variant that carries nothing"
            )
    if len(carriers) > 1:
        findings.append(
            f"variants {sorted(carriers)} carry the marker; a role has at most "
            "one addon-carrier variant"
        )
    return carriers, findings


def _uncarried_static_addons(
    variants: list, required: list[str], carriers: set[int]
) -> list[tuple[int, str, object]]:
    """
    Args:
        variants: the role's parsed variant list.
        required: the ids of the statically enabled addons.
        carriers: the addon-carrier variants, exempt from the check.

    Returns:
        ``(variant index, addon id, pinned value)`` per variant from 2 on
        that does not pin a statically enabled addon to ``false``.
    """
    return [
        (index, addon_id, value)
        for index in range(2, len(variants))
        if index not in carriers
        for addon_id in required
        if (value := _pinned_enabled(variants[index], addon_id)) is not False
    ]


def _pinned_addons(variant) -> Mapping:
    """Return a variant entry's ``addons`` map, empty when it declares none.

    Args:
        variant: one entry of the variant list.
    """
    if not isinstance(variant, Mapping):
        return {}
    addons = variant.get("addons")
    return addons if isinstance(addons, Mapping) else {}


def _addons_by_role(roles_root: Path) -> dict:
    """Return ``{role: [addon file, ...]}`` for every addon not opted out.

    Args:
        roles_root: the repository's ``roles`` directory.
    """
    by_role: dict = {}
    for role, addon_file in iter_addon_files(roles_root):
        if is_suppressed_in_head(read_text(str(addon_file)).splitlines(), _RULE):
            continue
        by_role.setdefault(role, []).append(addon_file)
    return by_role


def unexercised_addons(roles_root: Path) -> list[str]:
    """Return one line per optional addon the role's variants never flip.

    Args:
        roles_root: the repository's ``roles`` directory.
    """
    findings: list[str] = []
    for role, addon_files in sorted(_addons_by_role(roles_root).items()):
        variants = _variants(roles_root / role) or [{}]
        for addon_file in addon_files:
            spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
            if not isinstance(spec, Mapping) or spec.get("required") is True:
                continue
            base = spec.get("enabled", False)
            states = []
            for variant in variants:
                entry = _pinned_addons(variant).get(addon_file.stem)
                pinned = entry.get("enabled") if isinstance(entry, Mapping) else None
                states.append(base if pinned is None else pinned)
            if any(isinstance(state, str) for state in states):
                if len(variants) > 1:
                    continue
            elif {True, False} <= {bool(state) for state in states}:
                continue
            findings.append(
                f"- {role}/{ROLE_DIR_META_ADDONS}/{addon_file.stem}.yml resolves to "
                f"{states!r} across {len(variants)} variant(s)"
            )
    return findings


class TestAddonsVariantPinning(unittest.TestCase):
    def _roles(self) -> dict:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")
        return _addons_by_role(roles_root)

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
            carriers, _ = _addon_carriers(
                read_text(str(role_dir / ROLE_FILE_META_VARIANTS)), variants, required
            )
            findings.extend(
                f"- {role}/{ROLE_FILE_META_VARIANTS}: variant {index} pins "
                f"{addon_id!r} as {value!r}, variant 1 disables it"
                for index, addon_id, value in _uncarried_static_addons(
                    variants, required, carriers
                )
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
            f"Per-addon opt-out: `# nocheck: {_RULE}` with a reason. The role's "
            f"one addon-carrier variant keeps them on with `# nocheck: {_RULE} "
            "<reason>` on its `addons:` line."
        )

    def test_every_addon_carrier_marker_is_valid(self) -> None:
        findings: list[str] = []
        for role, addon_files in sorted(self._roles().items()):
            role_dir = PROJECT_ROOT / "roles" / role
            path = role_dir / ROLE_FILE_META_VARIANTS
            if not path.is_file():
                continue
            required = sorted(f.stem for f in addon_files if _base_enabled(f) is True)
            _, problems = _addon_carriers(
                read_text(str(path)), _variants(role_dir), required
            )
            findings.extend(
                f"- {role}/{ROLE_FILE_META_VARIANTS}: {p}" for p in problems
            )

        if not findings:
            return

        self.fail(
            f"`# nocheck: {_RULE}` on a variant's own `addons:` line names the "
            "role's one addon-carrier variant, which keeps the static addons on. "
            "It needs a reason, marks one variant only and never variant 0 or 1, "
            "requires variant 0 to keep the static addons off, and must leave at "
            "least one of them on:\n\n" + "\n".join(findings)
        )

    def _carriers(
        self, marked: Mapping[int, str], variants: list
    ) -> tuple[set[int], list[str]]:
        return _addon_carriers(
            "".join(f"- addons: {{}}{marked.get(index, '')}\n" for index in range(5)),
            variants,
            ["calendar"],
        )

    def _five_variants(self) -> list:
        off = {"calendar": {"enabled": False}}
        return [
            {"addons": off},
            {"addons": off},
            {"addons": off},
            {"addons": {}},
            {"addons": off},
        ]

    def test_a_marked_carrier_keeps_the_static_addons(self) -> None:
        carriers, problems = self._carriers(
            {3: f" # nocheck: {_RULE} budget split"}, self._five_variants()
        )
        self.assertEqual((carriers, problems), ({3}, []))
        self.assertEqual(
            _uncarried_static_addons(self._five_variants(), ["calendar"], carriers),
            [],
        )

    def test_negative_control_an_unmarked_carrier_fails(self) -> None:
        carriers, _ = self._carriers({}, self._five_variants())
        self.assertEqual(
            _uncarried_static_addons(self._five_variants(), ["calendar"], carriers),
            [(3, "calendar", None)],
        )

    def test_negative_control_a_second_marked_variant_fails(self) -> None:
        variants = self._five_variants()
        variants[4] = {"addons": {}}
        _, problems = self._carriers(
            {
                3: f" # nocheck: {_RULE} budget split",
                4: f" # nocheck: {_RULE} another split",
            },
            variants,
        )
        self.assertEqual(
            problems,
            [
                (
                    "variants [3, 4] carry the marker; a role has at most one "
                    "addon-carrier variant"
                )
            ],
        )

    def test_negative_control_a_marker_without_a_reason_fails(self) -> None:
        _, problems = self._carriers({3: f" # nocheck: {_RULE}"}, self._five_variants())
        self.assertEqual(
            problems,
            ["variant 3 carries the marker without a reason of at least 10 characters"],
        )

    def test_negative_control_a_too_short_reason_fails(self) -> None:
        _, problems = self._carriers(
            {3: f" # nocheck: {_RULE} split"}, self._five_variants()
        )
        self.assertEqual(
            problems,
            ["variant 3 carries the marker without a reason of at least 10 characters"],
        )

    def test_negative_control_a_marker_on_variant_1_fails(self) -> None:
        variants = self._five_variants()
        variants[1] = {"addons": {}}
        _, problems = self._carriers({1: f" # nocheck: {_RULE} owns the set"}, variants)
        self.assertEqual(
            problems,
            ["variant 1 carries the marker, but variant 1 owns the static-off set"],
        )

    def test_negative_control_a_carrier_beside_a_static_on_baseline_fails(
        self,
    ) -> None:
        variants = self._five_variants()[:3]
        variants[0] = {}
        variants[2] = {"addons": {}}
        _, problems = self._carriers({2: f" # nocheck: {_RULE} budget split"}, variants)
        self.assertEqual(
            problems,
            ["variant 2 carries the marker, but v0 already carries the static addons"],
        )

    def test_negative_control_a_stale_carrier_marker_fails(self) -> None:
        _, problems = self._carriers(
            {4: f" # nocheck: {_RULE} budget split"}, self._five_variants()
        )
        self.assertEqual(
            problems,
            ["variant 4: carrier marker on a variant that carries nothing"],
        )

    def test_negative_control_a_marker_off_the_addons_line_counts_nothing(
        self,
    ) -> None:
        text = (
            "- addons: {}\n- addons: {}\n- addons: {}\n"
            f"# Variant 3: heading # nocheck: {_RULE} budget split\n"
            "- services:\n"
            f"    tor: # nocheck: {_RULE} budget split\n"
            "      enabled: true\n"
            "  addons: {}\n"
        )
        variants = self._five_variants()[:4]
        self.assertEqual(_addon_carriers(text, variants, ["calendar"]), (set(), []))

    def test_a_marker_on_a_block_variants_addons_line_counts(self) -> None:
        text = (
            "- addons: {}\n- addons: {}\n- addons: {}\n"
            "- services:\n"
            "    tor:\n"
            "      enabled: true\n"
            f"  addons: {{}} # nocheck: {_RULE} budget split\n"
        )
        variants = self._five_variants()[:4]
        self.assertEqual(_addon_carriers(text, variants, ["calendar"]), ({3}, []))

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

    def test_every_optional_addon_takes_both_states(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")
        for finding in unexercised_addons(roles_root):
            gha_warning(
                f"{finding.removeprefix('- ')}: no variant switches it on and "
                f"off; pin it in meta/variants.yml or opt out with "
                f"`# nocheck: {_RULE}` and a reason",
                title="Optional addon never exercised in both states",
            )

    def test_the_state_rule_reports_each_unexercised_addon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_root = Path(tmp)
            for role, variants in (
                ("web-app-one", None),
                ("web-app-two", "- {}\n- addons:\n    flipped:\n      enabled: true\n"),
            ):
                addons = roles_root / role / ROLE_DIR_META_ADDONS
                addons.mkdir(parents=True)
                if variants is not None:
                    (roles_root / role / ROLE_FILE_META_VARIANTS).write_text(
                        variants, encoding="utf-8"
                    )
                for name, body in (
                    ("off", "enabled: false\n"),
                    ("on", "enabled: true\n"),
                    ("dyn", "enabled: \"{{ x('services.a.enabled') }}\"\n"),
                    ("core", "required: true\n"),
                    ("flipped", "enabled: false\n"),
                    ("exempt", f"# nocheck: {_RULE} paid only\nenabled: false\n"),
                ):
                    (addons / f"{name}.yml").write_text(body, encoding="utf-8")

            findings = unexercised_addons(roles_root)

        flagged = {line.split(" resolves")[0].removeprefix("- ") for line in findings}
        self.assertEqual(
            flagged,
            {f"web-app-one/{ROLE_DIR_META_ADDONS}/{n}.yml" for n in ("dyn", "flipped")}
            | {
                f"{role}/{ROLE_DIR_META_ADDONS}/{n}.yml"
                for role in ("web-app-one", "web-app-two")
                for n in ("off", "on")
            },
        )


if __name__ == "__main__":
    unittest.main()
