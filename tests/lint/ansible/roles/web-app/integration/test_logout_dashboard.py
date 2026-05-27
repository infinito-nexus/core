"""Integration guard: every ``web-app-*`` role MUST declare
``services.logout`` AND ``services.dashboard`` activated (both
``enabled`` and ``shared`` truthy — literal ``true`` or the dynamic
``"{{ '<role>' in group_names }}"`` form). Roles that legitimately
have no logout / no dashboard tile can opt out with a per-service
``# nocheck: logout`` / ``# nocheck: dashboard`` marker on the line
directly above the service key, paired with explicit
``enabled: false`` and ``shared: false``.

Same shape as ``test_email``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.services.registry import is_explicit_truth
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_ROLE_PREFIX = "web-app-"

# Roles that ARE the providers — exempt by definition (their own
# services.yml declares the primary entity, not a consumer reference).
_PROVIDER_EXEMPT: set[str] = {
    "web-app-dashboard",
}


def _service_conf(config_path: Path, key: str) -> dict:
    if not config_path.is_file():
        return {}
    try:
        parsed = load_yaml_any(str(config_path), default_if_missing={}) or {}
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    svc = parsed.get(key, {}) or {}
    return svc if isinstance(svc, dict) else {}


def _has_opt_out(config_path: Path, key: str) -> bool:
    """Opt-out for ``services.<key>`` requires all three:

    1. ``services.<key>.enabled`` is False
    2. ``services.<key>.shared`` is False
    3. ``# nocheck: <key>`` on the nearest non-empty line directly
       above the ``<key>:`` line in the raw YAML source.
    """
    if not config_path.is_file():
        return False
    try:
        text = read_text(str(config_path))
    except (OSError, UnicodeDecodeError):
        return False

    lines = text.splitlines()
    key_line_re = re.compile(rf"^(\s*){re.escape(key)}:\s*(#.*)?$")
    annotated = any(
        key_line_re.match(line)
        and is_suppressed_at(lines, idx + 1, key, mode="line-above")
        for idx, line in enumerate(lines)
    )
    if not annotated:
        return False

    try:
        parsed = load_yaml_str(text) or {}
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    svc = parsed.get(key, {}) or {}
    return svc.get("enabled") is False and svc.get("shared") is False


class TestWebAppLogoutDashboardIntegration(unittest.TestCase):
    """For every ``web-app-*`` role, ``services.logout`` and
    ``services.dashboard`` MUST have both ``enabled`` and ``shared``
    truthy (literal ``true`` or ``"{{ '<role>' in group_names }}"``),
    OR carry an explicit ``# nocheck: <key>`` opt-out paired with both
    flags ``false``.
    """

    def _check_service_activated(self, role_path: Path, key: str) -> str | None:
        """Return an error string if ``services.<key>`` is neither
        activated nor opted out; else ``None``."""
        config = role_path / ROLE_FILE_META_SERVICES
        svc = _service_conf(config, key)
        if is_explicit_truth(svc.get("enabled")) and is_explicit_truth(
            svc.get("shared")
        ):
            return None
        if _has_opt_out(config, key):
            return None

        rel = (
            config.relative_to(PROJECT_ROOT).as_posix()
            if config.is_file()
            else role_path.relative_to(PROJECT_ROOT).as_posix()
        )
        missing: list[str] = []
        if not is_explicit_truth(svc.get("enabled")):
            missing.append("enabled")
        if not is_explicit_truth(svc.get("shared")):
            missing.append("shared")
        return (
            f"[{role_path.name}] {rel}: services.{key} is not activated "
            f"(missing truthy {', '.join(missing) or 'flags'}). "
            f"Set both flags to ``true`` or the dynamic "
            f"``\"{{{{ '<role>' in group_names }}}}\"`` form, OR opt out "
            f"with a ``# nocheck: {key}`` comment on the line "
            f"directly above ``{key}:`` and set both flags to ``false``."
        )

    def test_logout_activated_or_opted_out(self):
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(roles_dir.is_dir(), f"missing: {roles_dir}")

        errors: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith(_ROLE_PREFIX)):
                continue
            if role_path.name in _PROVIDER_EXEMPT:
                continue
            err = self._check_service_activated(role_path, "logout")
            if err:
                errors.append(err)
        if errors:
            self.fail(
                "Web-app roles must declare services.logout activated:\n\n"
                + "\n".join(errors)
            )

    def test_dashboard_activated_or_opted_out(self):
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(roles_dir.is_dir(), f"missing: {roles_dir}")

        errors: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith(_ROLE_PREFIX)):
                continue
            if role_path.name in _PROVIDER_EXEMPT:
                continue
            err = self._check_service_activated(role_path, "dashboard")
            if err:
                errors.append(err)
        if errors:
            self.fail(
                "Web-app roles must declare services.dashboard activated:\n\n"
                + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
