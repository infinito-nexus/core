"""Lint: a consumer gates a swappable provider's service on its selector.

Some service keys are served by whichever role a ``*_PROVIDER`` variable in
``group_vars/all`` selects: ``MAIL_PROVIDER`` picks the role behind ``email``,
and both ``web-app-stalwart`` and ``web-app-mailu`` declare that key. A
consumer whose ``services.email`` flag reads ``'web-app-mailu' in group_names``
stays off on every host where the variable selects the other provider, even
though mail is served there.

The key to selector mapping is read, not listed: every top-level
``*_PROVIDER`` variable whose value is a role the service registry knows maps
each key that role declares (its primary key plus ``covers:``) to that
variable. A new selector is covered as soon as it lands in ``group_vars``.

Required
--------

For every ``services.<key>`` in a ``meta/services.yml`` whose key a selector
picks, ``enabled`` and ``shared`` MUST NOT test ``'<role>' in group_names``
for a role that declares the key. The neutral form is
``"{{ <SELECTOR> in group_names }}"``. A role that itself declares the key is
exempt.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_role_to_covered_keys,
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
GROUP_VARS_DIR = PROJECT_ROOT / "group_vars" / "all"
_SELECTOR_SUFFIX = "_PROVIDER"
_FLAGS = ("enabled", "shared")
_ROLE_GATE = re.compile(r"""(['"])(?P<role>[^'"]+)\1\s+in\s+group_names""")


def selector_variables(
    group_vars: Mapping[str, object],
    role_keys: Mapping[str, list[str]],
) -> dict[str, str]:
    """Map every service key a provider selector picks to that selector.

    Args:
        group_vars: top-level variables of ``group_vars/all``.
        role_keys: role id to the service keys it declares, as
            :func:`build_role_to_covered_keys` returns them.

    Returns:
        ``{service key: selector variable name}``.
    """
    selectors: dict[str, str] = {}
    for name, value in group_vars.items():
        if not str(name).endswith(_SELECTOR_SUFFIX) or not isinstance(value, str):
            continue
        for key in role_keys.get(value.strip(), []):
            selectors[key] = str(name)
    return selectors


def concrete_provider_gates(
    role: str,
    services: Mapping[str, object],
    selectors: Mapping[str, str],
    role_keys: Mapping[str, list[str]],
) -> list[str]:
    """Return one finding per flag that gates a selected key on one provider.

    Args:
        role: the role owning ``services``.
        services: that role's ``meta/services.yml`` mapping.
        selectors: service key to selector variable, from
            :func:`selector_variables`.
        role_keys: role id to the service keys it declares.

    Returns:
        Human-readable findings, empty when every gate is provider-neutral.
    """
    findings: list[str] = []
    for key, entry in services.items():
        selector = selectors.get(str(key))
        if not selector or not isinstance(entry, Mapping):
            continue
        providers = {name for name, keys in role_keys.items() if key in keys}
        if role in providers:
            continue
        for flag in _FLAGS:
            gated = {m["role"] for m in _ROLE_GATE.finditer(str(entry.get(flag)))}
            findings.extend(
                f"{role}: services.{key}.{flag} tests '{provider}' in "
                f"group_names, which stays false wherever {selector} "
                f'selects another provider; use "{{{{ {selector} in '
                f'group_names }}}}"'
                for provider in sorted(gated & providers)
            )
    return findings


def _group_vars() -> dict[str, object]:
    merged: dict[str, object] = {}
    for path in sorted(GROUP_VARS_DIR.glob("*.yml")):
        data = load_yaml_any(str(path), default_if_missing={})
        if isinstance(data, Mapping):
            merged.update(data)
    return merged


def _role_keys() -> dict[str, list[str]]:
    return build_role_to_covered_keys(build_service_registry_from_roles_dir(ROLES_DIR))


def _consumer_services() -> list[tuple[str, Mapping]]:
    found = []
    for path in sorted(ROLES_DIR.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(path), default_if_missing={})
        if isinstance(services, Mapping):
            found.append((path.parent.parent.name, services))
    return found


_ROLE_KEYS = {
    "web-app-stalwart": ["email"],
    "web-app-mailu": ["mailu", "email"],
    "web-app-keycloak": ["sso"],
}
_SELECTORS = {"email": "MAIL_PROVIDER"}


def _gate(expression: str) -> dict[str, str]:
    return {"enabled": expression, "shared": expression}


class TestProviderNeutralGate(unittest.TestCase):
    def test_no_consumer_gates_a_selected_key_on_one_provider(self) -> None:
        role_keys = _role_keys()
        selectors = selector_variables(_group_vars(), role_keys)
        findings = [
            finding
            for role, services in _consumer_services()
            for finding in concrete_provider_gates(role, services, selectors, role_keys)
        ]
        self.assertEqual(
            [],
            findings,
            f"service flag(s) gated on one concrete provider ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_derives_a_selector_that_consumers_use(self) -> None:
        selectors = selector_variables(_group_vars(), _role_keys())
        consumed = [
            role
            for role, services in _consumer_services()
            if any(key in selectors for key in services)
        ]
        self.assertTrue(
            consumed,
            "no *_PROVIDER variable in group_vars/all selects a key any role "
            "consumes, so the rule would pass vacuously; check that the scan "
            "still reads group_vars and the service registry",
        )

    def test_a_gate_on_the_retired_provider_is_flagged(self) -> None:
        findings = concrete_provider_gates(
            "web-app-weblate",
            {"email": _gate("{{ 'web-app-mailu' in group_names }}")},
            _SELECTORS,
            _ROLE_KEYS,
        )
        self.assertEqual(2, len(findings))

    def test_a_gate_on_the_default_provider_is_flagged(self) -> None:
        findings = concrete_provider_gates(
            "web-app-weblate",
            {"email": _gate('{{ "web-app-stalwart" in group_names }}')},
            _SELECTORS,
            _ROLE_KEYS,
        )
        self.assertEqual(2, len(findings))

    def test_the_neutral_gate_is_accepted(self) -> None:
        findings = concrete_provider_gates(
            "web-app-weblate",
            {"email": _gate("{{ MAIL_PROVIDER in group_names }}")},
            _SELECTORS,
            _ROLE_KEYS,
        )
        self.assertEqual([], findings)

    def test_the_provider_role_itself_is_accepted(self) -> None:
        findings = concrete_provider_gates(
            "web-app-mailu",
            {"email": _gate("{{ 'web-app-mailu' in group_names }}")},
            _SELECTORS,
            _ROLE_KEYS,
        )
        self.assertEqual([], findings)

    def test_a_key_no_selector_picks_is_not_judged(self) -> None:
        findings = concrete_provider_gates(
            "web-app-weblate",
            {"sso": _gate("{{ 'web-app-keycloak' in group_names }}")},
            _SELECTORS,
            _ROLE_KEYS,
        )
        self.assertEqual([], findings)

    def test_a_selector_maps_every_key_its_role_declares(self) -> None:
        self.assertEqual(
            {"mailu": "MAIL_PROVIDER", "email": "MAIL_PROVIDER"},
            selector_variables({"MAIL_PROVIDER": "web-app-mailu"}, _ROLE_KEYS),
        )

    def test_a_variable_naming_no_provider_role_maps_nothing(self) -> None:
        self.assertEqual(
            {},
            selector_variables(
                {"DNS_PROVIDER": "localhost", "MAIL_ROLE": "web-app-stalwart"},
                _ROLE_KEYS,
            ),
        )


if __name__ == "__main__":
    unittest.main()
