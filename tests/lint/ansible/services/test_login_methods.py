"""Lint: every sign-in method of an application follows the login-method table.

A role whose own sign-in page sits behind native OIDC or SAML declares
``<entity>.login.method.<method>.enabled`` in ``meta/services.yml`` for every
method the page can offer, and each default is the ``login_method`` lookup of
that role and method. The lookup holds the one table that decides which methods
a mode turns on (``utils.roles.applications.login``), so a role cannot drift
from it; an inventory still overrides a single flag.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: login-methods`` plus a reason, on or directly above the role's
  ``sso:`` key, for a role whose sign-in offers one method only.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import has_rule_with_reason
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.scan import iter_role_dirs
from utils.roles.applications.login import METHODS
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_RULE = "login-methods"
_NATIVE_SSO_FLAVORS = frozenset({"oidc", "saml"})


def _expected(application_id: str, method: str) -> str:
    return f"{{{{ lookup('login_method', '{application_id}', '{method}') }}}}"


def _normalized(value: object) -> str:
    return " ".join(str(value).split())


def _services(role_dir: Path) -> tuple[Mapping, list[str]] | None:
    path = role_dir / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return None
    data = load_yaml_any(str(path))
    if not isinstance(data, Mapping):
        return None
    return data, read_text(str(path)).splitlines()


def _sso_line(lines: list[str]) -> int | None:
    return next(
        (n for n, line in enumerate(lines, 1) if line.startswith("sso:")), None
    )


def _method_findings(application_id: str, login: object) -> list[str]:
    methods = login.get("method") if isinstance(login, Mapping) else None
    if not isinstance(methods, Mapping) or not methods:
        return ["login.method is not a non-empty mapping"]
    findings = []
    for method, spec in methods.items():
        if method not in METHODS:
            findings.append(f"login.method.{method} is not one of {', '.join(METHODS)}")
            continue
        if not isinstance(spec, Mapping) or set(spec) != {"enabled"}:
            findings.append(f"login.method.{method} must hold exactly `enabled`")
            continue
        expected = _expected(application_id, method)
        if _normalized(spec["enabled"]) != expected:
            findings.append(
                f"login.method.{method}.enabled is {spec['enabled']!r}, expected {expected!r}"
            )
    return findings


class TestLoginMethods(unittest.TestCase):
    def test_declared_methods_default_through_the_lookup(self):
        violations = []
        for role_dir in iter_role_dirs():
            loaded = _services(role_dir)
            if loaded is None:
                continue
            services, _ = loaded
            for entity, config in services.items():
                if isinstance(config, Mapping) and "login" in config:
                    violations.extend(
                        f"{role_dir.name}/{entity}: {finding}"
                        for finding in _method_findings(role_dir.name, config["login"])
                    )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_native_sso_roles_declare_their_methods(self):
        missing = []
        for role_dir in iter_role_dirs():
            loaded = _services(role_dir)
            if loaded is None:
                continue
            services, lines = loaded
            sso = services.get("sso")
            if not isinstance(sso, Mapping) or sso.get("flavor") not in _NATIVE_SSO_FLAVORS:
                continue
            entity = services.get(entity_name(role_dir.name))
            if isinstance(entity, Mapping) and "login" in entity:
                continue
            line = _sso_line(lines)
            if line is not None and has_rule_with_reason(lines, line, _RULE):
                continue
            missing.append(role_dir.name)
        self.assertEqual(
            missing,
            [],
            "roles with a native SSO sign-in but no "
            "<entity>.login.method block (declare it, or mark a one-method "
            f"sign-in with `# nocheck: {_RULE}` and a reason on its sso: key):\n"
            + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
