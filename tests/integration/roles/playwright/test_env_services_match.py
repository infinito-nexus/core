"""Integration guard: every service declared in a role's
``meta/services.yml`` MUST surface as a ``<NAME>_SERVICE_ENABLED=`` flag
in the same role's ``templates/playwright.env.j2``.

Scope
-----

Only roles that ship a ``templates/playwright.env.j2`` are checked.
A service entry counts as "declared" iff it carries an ``enabled:``
key. Bare config stubs (entries with only ``image:`` / ``version:`` /
``ports:`` / etc. and no ``enabled:`` key) are out of scope — they
are not gateable shared-service deps in the documented sense.

Why
---

Makes ``templates/playwright.env.j2`` the per-role
registry of gateable services for Playwright specs: a service that is
not declared as ``<NAME>_SERVICE_ENABLED=...`` cannot be gated, and
``service-gating.js`` will hard-fail any ``isServiceEnabled("<name>")``
call that targets an unregistered service. ``meta/services.yml`` is
the upstream source of truth for which services the role consumes;
this test enforces that the env-template registry stays in sync.

Suppression
-----------

A service entry MAY opt out via ``# nocheck: playwright-service-flag``
in the comment block immediately above its top-level key in
``meta/services.yml``. Use this only when a service legitimately
cannot or must not be gated from Playwright (for example the role's
own provider service (forbidden self-gate).
The catalog entry lives in
``docs/contributing/actions/testing/suppression.md``.

Globally-exempt services
------------------------

Services whose verification is owned by their own provider's
parameterised spec (``dashboard``, ``prometheus``)
are globally exempt: every consumer role declares them in
``meta/services.yml`` for inventory completeness, but the per-role
env templates intentionally do NOT render the
``<NAME>_SERVICE_ENABLED=`` flag because the persona scenarios no
longer gate on them. The provider specs
(``roles/web-app-{dashboard,prometheus}/files/playwright/playwright.spec.js``)
parameterise one assertion per consumer using the
``DASHBOARD_TARGET_ROLES_JSON`` / ``PROMETHEUS_TARGET_ROLES_JSON``
manifests rendered by the ``roles_with_service`` filter.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "playwright-service-flag"

_ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_ENV_KEY_LHS_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=", re.MULTILINE)

# SPOT-owned services: the provider's own spec parameterises
# one assertion per consumer via *_TARGET_ROLES_JSON, so consumer roles
# declare the service in `meta/services.yml` for inventory completeness
# but legitimately do NOT render `<NAME>_SERVICE_ENABLED=` in their env.
_SPOT_OWNED_SERVICES: frozenset[str] = frozenset({"dashboard", "prometheus"})


def _service_to_env_key(name: str) -> str:
    """Mirror of ``service-gating.js::envKey``: upper-case the name and
    collapse non-alphanumerics into ``_``, then suffix
    ``_SERVICE_ENABLED``."""
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()) + "_SERVICE_ENABLED"


def _suppressed_top_level_keys(file_path: Path) -> set[str]:
    """Return service keys whose preceding comment block carries the
    suppression marker. A blank line between marker and key breaks the
    association (mirrors ``test_dynamic_flags.py``)."""
    exceptions: set[str] = set()
    pending = False
    for raw_line in read_text(str(file_path)).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            if line_has_rule(raw_line, _RULE):
                pending = True
            continue
        if not stripped:
            pending = False
            continue
        is_top_level = not raw_line.startswith((" ", "\t"))
        if pending and is_top_level and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            if key:
                exceptions.add(key)
        pending = False
    return exceptions


def _env_keys_declared(env_text: str) -> set[str]:
    """Return every ``KEY=`` left-hand-side declared in a
    ``playwright.env.j2`` body. The same scan as
    ``web-app/playwright/test_env_keys_used.py`` but coarser — we only care
    whether the key appears, not its value or position."""
    return set(_ENV_KEY_LHS_RE.findall(env_text))


class TestPlaywrightEnvServicesMatch(unittest.TestCase):
    def test_every_services_yml_entry_has_a_service_flag(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            env_path = role_dir / _ENV_TEMPLATE_REL
            if not env_path.is_file():
                continue
            services_path = role_dir / ROLE_FILE_META_SERVICES
            if not services_path.is_file():
                continue

            try:
                services = load_yaml_any(services_path, default_if_missing={}) or {}
            except Exception as exc:
                offenders.append(f"{role_name}: services.yml parse error: {exc}")
                continue
            if not isinstance(services, dict):
                continue

            exempt = _suppressed_top_level_keys(services_path)
            declared_keys = _env_keys_declared(read_text(str(env_path)))

            for service_key, entry in services.items():
                if not isinstance(service_key, str):
                    continue
                if not isinstance(entry, dict):
                    continue
                if "enabled" not in entry:
                    continue
                if service_key in exempt:
                    continue
                # SPOT-owned services are globally exempt; the
                # provider spec parameterises one assertion per
                # consumer via the *_TARGET_ROLES_JSON manifest, so
                # the per-role env flag is intentionally not rendered.
                if (
                    service_key in _SPOT_OWNED_SERVICES
                    and role_name != f"web-app-{service_key}"
                ):
                    continue

                expected_flag = _service_to_env_key(service_key)
                if expected_flag in declared_keys:
                    continue

                offenders.append(
                    f"{role_name}: meta/services.yml declares '{service_key}' "
                    f"with `enabled:` but {_ENV_TEMPLATE_REL} has no "
                    f"`{expected_flag}=...` line. Add the flag (e.g. "
                    f"`{expected_flag}={{{{ ... }}}}`) or mark the service "
                    f"with `# nocheck: {_RULE}` above its key in "
                    f"meta/services.yml."
                )

        if offenders:
            self.fail(
                "Services declared in meta/services.yml but not registered "
                "as `<NAME>_SERVICE_ENABLED=` in playwright.env.j2:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
