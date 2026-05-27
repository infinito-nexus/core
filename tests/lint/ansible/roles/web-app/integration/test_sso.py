"""Integration guard: every ``web-app-*`` role MUST front its login
flow with one of the two project-wide SSO paths:

* native OIDC — ``services.oidc`` activated (both ``enabled`` and
  ``shared`` truthy: literal ``true`` or the dynamic
  ``"{{ 'web-app-keycloak' in group_names }}"`` form), OR
* an oauth2-proxy in front of Keycloak — ``services.oauth2``
  activated.

If ``services.oidc`` carries an explicit opt-out marker
(``# nocheck: oidc`` directly above the key,
paired with ``enabled: false`` and ``shared: false``), then
``services.oauth2`` MUST be activated to fill the gap. Roles that
legitimately have no login flow at all (static-content sites, etc.)
opt out of BOTH by carrying both ``# nocheck: oidc`` AND ``# nocheck: oauth2``
markers.

The provider roles themselves (``web-app-keycloak``,
``web-app-oauth2-proxy``) are exempt by definition.
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

# Provider roles — exempt from the SSO integration check (they ARE
# the providers).
_PROVIDER_EXEMPT: set[str] = {
    "web-app-keycloak",
    "web-app-oauth2-proxy",
}


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
    3. ``# noqa: <key>`` (or ``# nocheck: <key>``) on the line directly
       above the ``<key>:`` line in the raw YAML source.
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
    """Every web-app-* role must offer SSO via oidc OR oauth2-proxy,
    or carry explicit opt-out markers on both."""

    def test_oidc_or_oauth2_activated(self):
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

            oidc = _service_conf(parsed, "oidc")
            oauth2 = _service_conf(parsed, "oauth2")

            oidc_active = _is_activated(oidc)
            oauth2_active = _is_activated(oauth2)

            if oidc_active or oauth2_active:
                continue  # at least one SSO path activated → pass

            oidc_opted_out = _is_explicit_opt_out(text, parsed, "oidc")
            oauth2_opted_out = _is_explicit_opt_out(text, parsed, "oauth2")

            if oidc_opted_out and oauth2_opted_out:
                continue  # both explicitly opted out → no-login app

            rel = config.relative_to(root).as_posix()
            errors.append(
                f"[{role_path.name}] {rel}: neither services.oidc nor "
                f"services.oauth2 is activated. "
                f"Set one of them to ``enabled: true`` + ``shared: true`` "
                f"(literal or dynamic ``\"{{{{ '<role>' in group_names }}}}\"``), "
                f"OR if oidc is intentionally not used, opt it out with a "
                f"``# nocheck: oidc`` comment directly "
                f"above ``oidc:`` paired with ``enabled: false`` + "
                f"``shared: false`` AND activate ``services.oauth2``. "
                f"For roles with no login flow at all, opt out BOTH "
                f"``oidc`` and ``oauth2`` the same way."
            )

        if errors:
            self.fail(
                "Web-app roles must declare an SSO path "
                "(oidc OR oauth2-proxy):\n\n" + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
