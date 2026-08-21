"""Integration guard: every ``web-app-*`` role MUST declare an SSO
path under the unified block:

* ``services.sso`` activated (both ``enabled`` and ``shared`` truthy:
  literal ``true`` or the dynamic
  ``"{{ 'web-app-keycloak' in group_names }}"`` form), with an
  explicit ``flavor`` in ``{oidc, oauth2, saml}``.

Roles that legitimately have no login flow at all (static-content
sites, etc.) opt out by carrying ``# nocheck: sso`` directly above
the ``sso:`` key paired with ``enabled: false`` + ``shared: false``.

The provider role itself (``web-app-keycloak``) is exempt by
definition.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.services.registry import is_explicit_truth
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_ROLE_PREFIX = "web-app-"

_PROVIDER_EXEMPT: set[str] = {
    "web-app-keycloak",
}

_VALID_FLAVORS = {"oidc", "oauth2", "saml"}


def _parsed_yaml(text: str) -> dict:
    try:
        parsed = load_yaml_str(text) or {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _service_conf(parsed: dict, key: str) -> dict:
    svc = parsed.get(key, {}) or {}
    return svc if isinstance(svc, dict) else {}


def _is_activated(svc: dict) -> bool:
    return is_explicit_truth(svc.get("enabled")) and is_explicit_truth(
        svc.get("shared")
    )


def _is_explicit_opt_out(text: str, parsed: dict, key: str) -> bool:
    """Opt-out for ``services.<key>`` requires all three:

    1. ``services.<key>.enabled`` is False
    2. ``services.<key>.shared`` is False
    3. ``# nocheck: <key>`` on the line directly above the ``<key>:``
       line in the raw YAML source.
    """
    lines = text.splitlines()
    key_line_re = re.compile(rf"^(\s*){re.escape(key)}:\s*(#.*)?$")
    annotated = any(
        key_line_re.match(line)
        and is_suppressed_at(lines, idx + 1, key, mode="line-above")
        for idx, line in enumerate(lines)
    )
    if not annotated:
        return False
    svc = _service_conf(parsed, key)
    return svc.get("enabled") is False and svc.get("shared") is False


class TestWebAppSsoIntegration(unittest.TestCase):
    """Every web-app-* role must offer SSO via the unified `sso:` block,
    or carry an explicit opt-out marker."""

    def test_sso_activated_with_explicit_flavor(self):
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(roles_dir.is_dir(), f"missing: {roles_dir}")

        errors: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith(_ROLE_PREFIX)):
                continue
            if role_path.name in _PROVIDER_EXEMPT:
                continue

            config = role_path / ROLE_FILE_META_SERVICES
            if not config.is_file():
                errors.append(f"[{role_path.name}] missing meta/services.yml")
                continue

            try:
                text = read_text(str(config))
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"[{role_path.name}] cannot read services.yml: {exc}")
                continue

            try:
                parsed = load_yaml_any(str(config), default_if_missing={}) or {}
            except Exception as exc:
                errors.append(f"[{role_path.name}] yaml parse error: {exc}")
                continue
            if not isinstance(parsed, dict):
                continue

            sso = _service_conf(parsed, "sso")
            if _is_activated(sso):
                flavor = sso.get("flavor")
                if flavor not in _VALID_FLAVORS:
                    rel = config.relative_to(root).as_posix()
                    errors.append(
                        f"[{role_path.name}] {rel}: services.sso is activated "
                        f"but `flavor` is missing or invalid (got {flavor!r}). "
                        f"Add `flavor: oidc` (default) or one of "
                        f"{sorted(_VALID_FLAVORS)}."
                    )
                continue

            if _is_explicit_opt_out(text, parsed, "sso"):
                continue

            rel = config.relative_to(root).as_posix()
            errors.append(
                f"[{role_path.name}] {rel}: services.sso is not activated. "
                f"Set ``enabled: true`` + ``shared: true`` (literal or "
                f"dynamic ``\"{{{{ 'web-app-keycloak' in group_names }}}}\"``) "
                f"with an explicit ``flavor`` in {sorted(_VALID_FLAVORS)}, "
                f"OR opt out with a ``# nocheck: sso`` comment directly "
                f"above ``sso:`` paired with ``enabled: false`` + "
                f"``shared: false``."
            )

        if errors:
            self.fail(
                "Web-app roles must declare an SSO path under "
                "``services.sso``:\n\n" + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
