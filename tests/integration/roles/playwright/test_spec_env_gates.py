"""Integration guard: every ``<NAME>_SERVICE_ENABLED=`` flag declared
in a role's ``templates/playwright.env.j2`` MUST be gated by at least
one ``service-gating`` helper call in the role's
``files/playwright/playwright.spec.js``.

Scope
-----

Only roles that ship both the env template and the spec are checked.
Roles with an env template but no spec are already flagged by
``tests/lint/ansible/roles/web-app/playwright/test_env_keys_used.py``.

A "gate" is any one of these helper invocations referencing the
service name (case-insensitive, whitespace tolerated)::

    requireService("name", ...)
    skipUnlessServiceEnabled("name")
    isServiceEnabled("name")
    isServiceDisabledReason("name")

The helper derives the env key with ``name.toUpperCase().replace(/
[^A-Z0-9]+/g, "_") + "_SERVICE_ENABLED"`` (see
``roles/test-e2e-playwright/files/service-gating.js``). This test
mirrors that derivation in Python and matches each declared env flag
against the set of env keys consumed by the spec.

Why
---

Without this guard a role can declare ``OIDC_SERVICE_ENABLED`` in its
env template, run with ``OIDC_SERVICE_ENABLED=false``, and still have
its OIDC scenarios execute and fail — because nothing in the spec
actually consults the flag. Mandates the gate; this
test makes "flag declared but never gated" a hard error rather than a
silent regression.

Suppression
-----------

An env-template line MAY opt out via
``# nocheck: playwright-service-gate`` placed on the same line as the
``<NAME>_SERVICE_ENABLED=...`` declaration or in the comment block
immediately above it. Use only when the flag legitimately exists for
non-spec consumers (e.g. shared deploy fixtures) but the spec has no
scenario to gate. The catalog entry lives in
``docs/contributing/actions/testing/suppression.md``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "playwright-service-gate"

_ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_SPEC_FILE_REL = ROLE_FILE_PLAYWRIGHT_SPEC
_SHARED_PERSONAS_DIR = "roles/test-e2e-playwright/files/personas"
_PERSONA_RUNNERS: tuple[str, ...] = ("runGuestFlow", "runBiberFlow", "runAdminFlow")

_FLAG_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)_SERVICE_ENABLED\s*=")
_HELPER_CALL_RE = re.compile(
    r"\b(?:requireService|skipUnlessServiceEnabled|isServiceEnabled|"
    r"isServiceDisabledReason|safeSkipUnlessEnabled|safeIsEnabled)\s*\(\s*['\"]([^'\"]+)['\"]"
)


def _service_to_env_key_root(name: str) -> str:
    """Reduce a helper-call argument to its env-key root (without the
    ``_SERVICE_ENABLED`` suffix), matching ``service-gating.js::envKey``."""
    return re.sub(r"[^A-Z0-9]+", "_", name.upper())


def _flag_lines_in_env(env_path: Path) -> list[tuple[int, str]]:
    """Return ``[(1-based line_no, root_key)]`` for each
    ``<ROOT>_SERVICE_ENABLED=...`` line in the env template, where
    ``root_key`` excludes the ``_SERVICE_ENABLED`` suffix."""
    text = read_text(str(env_path))
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        m = _FLAG_LINE_RE.match(line)
        if m:
            out.append((idx, m.group(1)))
    return out


def _gated_roots_in_spec(spec_path: Path) -> set[str]:
    """Return the set of env-key roots gated somewhere in the spec
    (any of the four helper APIs, with the helper's own canonicalisation).

    Roles may keep the spec monolithic or split each `test(...)` block
    into its own `test-<scenario>.js` companion module that
    `playwright.spec.js` `require()`s; gates declared in any sibling
    `.js` file in the role's playwright directory count as consumed
    by the spec.

    When the spec imports a persona-flow runner from `./personas`
    (`runGuestFlow` / `runBiberFlow` / `runAdminFlow`), the gates
    inside the shared personas directory count as consumed by the spec
    too — every persona scenario fully drives the underlying
    `skipUnlessServiceEnabled('...')` chain via shared helpers.
    """
    spec_dir_texts = [
        read_text(str(js_path)) for js_path in sorted(spec_path.parent.glob("*.js"))
    ]
    combined_text = "\n".join(spec_dir_texts)
    roots: set[str] = {
        _service_to_env_key_root(name)
        for name in _HELPER_CALL_RE.findall(combined_text)
    }

    if any(runner in combined_text for runner in _PERSONA_RUNNERS):
        personas_prefix = str(PROJECT_ROOT / _SHARED_PERSONAS_DIR) + "/"
        for persona_path in sorted(iter_project_files(extensions=(".js",))):
            if not persona_path.startswith(personas_prefix):
                continue
            persona_text = read_text(persona_path)
            roots.update(
                _service_to_env_key_root(name)
                for name in _HELPER_CALL_RE.findall(persona_text)
            )

    return roots


class TestPlaywrightSpecGatesEnvFlags(unittest.TestCase):
    def test_every_env_flag_is_gated_by_spec(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            env_path = role_dir / _ENV_TEMPLATE_REL
            spec_path = role_dir / _SPEC_FILE_REL
            if not env_path.is_file() or not spec_path.is_file():
                continue

            env_lines = read_text(str(env_path)).splitlines()
            gated_roots = _gated_roots_in_spec(spec_path)

            for line_no, root in _flag_lines_in_env(env_path):
                if is_suppressed_at(env_lines, line_no, _RULE):
                    continue
                if root in gated_roots:
                    continue

                offenders.append(
                    f"{role_name}: {_ENV_TEMPLATE_REL}:{line_no} declares "
                    f"`{root}_SERVICE_ENABLED=` but {_SPEC_FILE_REL} has "
                    f'no `requireService("{root.lower()}", …)` / '
                    f'`skipUnlessServiceEnabled("{root.lower()}")` / '
                    f'`isServiceEnabled("{root.lower()}")` / '
                    f'`isServiceDisabledReason("{root.lower()}")` call. '
                    f"Add a gated test or mark the flag with "
                    f"`# nocheck: {_RULE}`."
                )

        if offenders:
            self.fail(
                "Playwright env flags declared but never gated by the "
                "spec:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
