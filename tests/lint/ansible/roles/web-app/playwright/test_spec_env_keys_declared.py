"""Lint that every env key referenced by ``roles/<role>/files/playwright/playwright.spec.js``
is declared in the sibling ``roles/<role>/templates/playwright.env.j2``.

Counterpart to ``test_env_keys_used.py``: that one catches *dead*
declarations (env declared, spec never reads); this one catches *missing*
declarations (spec reads, env never declares) — the failure mode that
slipped through with ``DASHBOARD_BASE_URL`` on ``web-app-kix`` and made
every persona test crash on the preamble assertion.

Excluded from the check:

* Names matched by ``_RUNTIME_ENV_NAMES`` — Node.js / Playwright /
  test-runner / CI-injected variables that originate outside the
  rendered ``.env`` and would NEVER belong in a role template.
* Names matched by ``_SHARED_HELPER_PREFIXES`` — keys consumed only
  by the shared helpers under ``roles/test-e2e-playwright/files/``
  (e.g. ``PLAYWRIGHT_*`` runtime knobs) and rendered at deploy time
  by the test-e2e-playwright role itself, not the per-app templates.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_KEY_LHS_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=")

# `process.env.<NAME>` / `process.env["<NAME>"]` / `process.env['<NAME>']`
# / `readEnv("<NAME>")` / `readEnv('<NAME>')`.
_ENV_REF_RE = re.compile(
    r"""
    process\.env\.(?P<dot>[A-Z_][A-Z0-9_]*)\b
    | process\.env\[\s*['"](?P<bracket>[A-Z_][A-Z0-9_]*)['"]\s*\]
    | readEnv\(\s*['"](?P<helper>[A-Z_][A-Z0-9_]*)['"]\s*\)
    """,
    re.VERBOSE,
)

# Runtime-injected / Playwright-internal names that the role's `.env.j2`
# is NOT expected to declare. Origins:
# * Node.js runtime itself: NODE_ENV, NODE_TLS_*, NODE_DEBUG, …
# * Playwright runner: PLAYWRIGHT_*, PW_*, CI, DEBUG.
# * Test-harness flags injected by the deploy task (see
#   `roles/test-e2e-playwright/tasks/02_run_one.yml`, e.g.
#   `INFINITO_PLAYWRIGHT_KEEP`).
_RUNTIME_ENV_NAMES: frozenset[str] = frozenset(
    {
        "CI",
        "DEBUG",
        "INFINITO_PLAYWRIGHT_KEEP",
        "NODE_DEBUG",
        "NODE_ENV",
        "NODE_TLS_REJECT_UNAUTHORIZED",
        "PLAYWRIGHT_BROWSERS_PATH",
        "PLAYWRIGHT_HTML_REPORT",
        "PLAYWRIGHT_JSON_REPORT",
        "PW_TEST_HTML_REPORT_OPEN",
        "PWDEBUG",
        "PWTEST_DEFAULT_TIMEOUT",
    }
)

# Prefixes consumed only by shared helpers under
# `roles/test-e2e-playwright/files/` and rendered by that role's own
# template / injection step, not by per-app `playwright.env.j2`.
_RUNTIME_ENV_PREFIXES: tuple[str, ...] = ()


def _is_runtime(name: str) -> bool:
    if name in _RUNTIME_ENV_NAMES:
        return True
    return any(name.startswith(p) for p in _RUNTIME_ENV_PREFIXES)


def _extract_env_keys(env_text: str) -> set[str]:
    """Same shape as `test_env_keys_used._extract_env_keys` but as a
    set — declaration order does not matter for this check."""
    keys: set[str] = set()
    for line in env_text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("{%", "{#")):
            continue
        m = _KEY_LHS_RE.match(stripped)
        if m:
            keys.add(m.group(1))
    return keys


def _extract_env_refs(js_text: str) -> set[str]:
    refs: set[str] = set()
    for m in _ENV_REF_RE.finditer(js_text):
        name = m.group("dot") or m.group("bracket") or m.group("helper")
        if name:
            refs.add(name)
    return refs


def _read_spec(spec_path: Path) -> str:
    """Read ONLY the role's `playwright.spec.js`. Other JS files under
    `<role>/files/` (e.g. `login-broker/server.js` for web-app-bluesky)
    are runtime app code, not test code — their `process.env` reads come
    from compose env, not from `playwright.env.j2`, and must not be
    matched against the per-role test contract."""
    return read_text(str(spec_path))


class TestPlaywrightSpecEnvKeysDeclared(unittest.TestCase):
    def test_spec_env_refs_declared_in_env_j2(self):
        roles_dir = PROJECT_ROOT / "roles"
        missing: list[str] = []

        for role_dir in sorted(roles_dir.iterdir()):
            if not role_dir.is_dir():
                continue
            spec_path = role_dir / ROLE_FILE_PLAYWRIGHT_SPEC
            if not spec_path.is_file():
                continue
            role_name = role_dir.name
            env_path = role_dir / "templates" / "playwright.env.j2"
            spec_rel = spec_path.relative_to(PROJECT_ROOT).as_posix()
            env_rel = env_path.relative_to(PROJECT_ROOT).as_posix()

            if not env_path.is_file():
                # `test_has_env` covers the missing-template case;
                # silently skip here so we do not double-report.
                continue

            declared = _extract_env_keys(read_text(str(env_path)))
            refs = _extract_env_refs(_read_spec(spec_path))

            for name in sorted(refs):
                if _is_runtime(name):
                    continue
                if name in declared:
                    continue
                missing.append(
                    f"{role_name}: '{name}' is read via process.env in "
                    f"{spec_rel} but never declared in {env_rel}"
                )

        if missing:
            self.fail(
                f"{len(missing)} env reference(s) lack a declaration in the "
                f"role's playwright.env.j2:\n" + "\n".join(f"- {m}" for m in missing)
            )
