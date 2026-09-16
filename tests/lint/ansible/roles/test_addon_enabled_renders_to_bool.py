"""Every addon ``enabled`` must render to a boolean, even on a bare scope.

Rationale
=========
``meta/addons/*.yml`` is rendered inside the applications SPOT and consumed as
``plugin_value.enabled | bool``. An expression that cannot resolve does not
fail: ``utils.templating.ansible._templar_render_best_effort`` returns the
string untouched, and for a value carrying a non-env ``lookup(`` it refuses the
fallback as well. The template text reaches the filter, which coerces it to
False and emits::

    [DEPRECATION WARNING]: The `bool` filter coerced invalid value
    "{{ ... }}" (str) to False.

The deploy gate fails on that warning, and the addon is off in every run that
did not warn loudly enough to be noticed. Run 34893363518, job 104153194109
lost web-app-nextcloud this way.

The check renders the whole applications map against a scope carrying only what
every run has -- group_vars plus the deployed role names -- and blanks ``API``
to the most hostile override an inventory may legally write. Anything that
survives as template text resolves only against something the render scope does
not carry.
"""

from __future__ import annotations

import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.applications import (
    _MERGED_APPLICATIONS_CACHE,
    get_merged_applications,
)
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_ADDONS_GLOB = "*/meta/addons/*.yml"
_BOOL_LITERALS = frozenset(
    {"true", "false", "yes", "no", "on", "off", "1", "0", "y", "n"}
)


def _role_names() -> list[str]:
    return sorted(
        path.name for path in (PROJECT_ROOT / "roles").iterdir() if path.is_dir()
    )


def _hostile_scope() -> dict[str, Any]:
    variables: dict[str, Any] = {}
    for path in sorted((PROJECT_ROOT / "group_vars" / "all").glob("*.yml")):
        data = load_yaml_any(path) or {}
        if isinstance(data, dict):
            variables.update(data)
    variables["group_names"] = _role_names()
    variables["API"] = {}
    return variables


def _rendered_addons() -> dict[str, dict[str, Any]]:
    variables = _hostile_scope()
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)

    _MERGED_APPLICATIONS_CACHE.clear()
    try:
        applications = get_merged_applications(
            variables=dict(variables), templar=templar
        )
    finally:
        _MERGED_APPLICATIONS_CACHE.clear()

    return {
        app_id: config["addons"]
        for app_id, config in applications.items()
        if isinstance(config, dict) and isinstance(config.get("addons"), dict)
    }


def _verdict(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if not isinstance(value, str):
        return f"is {type(value).__name__}, not a boolean"
    if "{{" in value or "{%" in value:
        return f"stayed template text: {value}"
    if value.strip().lower() not in _BOOL_LITERALS:
        return f"is not a boolean literal: {value!r}"
    return ""


class TestAddonEnabledRendersToBool(unittest.TestCase):
    def test_every_addon_enabled_resolves(self) -> None:
        findings = [
            f"  - roles/{app_id}/meta/addons/{addon_id}.yml: 'enabled' {verdict}"
            for app_id, addons in _rendered_addons().items()
            for addon_id, spec in sorted(addons.items())
            if isinstance(spec, dict)
            for verdict in [_verdict(spec.get("enabled"))]
            if verdict
        ]

        if findings:
            self.fail(
                f"{len(findings)} addon gate(s) do not render to a boolean on a "
                "scope without inventory extras, so '| bool' coerces the leftover "
                "text to False and the deploy fails on the deprecation warning:\n"
                + "\n".join(findings)
                + "\n\nResolve the value through a lookup that carries its own "
                "source instead of a variable the render scope may not hold: "
                "lookup('api_enabled', '<provider>') gates on credentials, "
                "lookup('config', ...) on another application's settings."
            )

    def test_the_scan_reaches_templated_gates(self) -> None:
        """A scope that resolved nothing, or addons without gates, passes for free."""
        templated = [
            path
            for path in sorted((PROJECT_ROOT / "roles").glob(_ADDONS_GLOB))
            if "{{" in str((load_yaml_any(path) or {}).get("enabled", ""))
        ]
        self.assertTrue(
            templated,
            "no addon declares a templated 'enabled', so the rule above is vacuous",
        )

        rendered = _rendered_addons()
        self.assertTrue(rendered, "no application carries addons; nothing was checked")


if __name__ == "__main__":
    unittest.main()
