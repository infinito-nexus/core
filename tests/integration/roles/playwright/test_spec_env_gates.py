"""Integration guard on the two directions of the service-gate contract.

Forwards: every ``<NAME>_SERVICE_ENABLED=`` flag declared in a role's
``templates/playwright.env.j2`` MUST be gated by at least one
``service-gating`` helper call in the role's
``files/playwright/playwright.spec.js``.

Backwards: every service a role's own specs gate through one of the
STRICT helpers MUST have its flag declared in that role's env
template. The strict helpers raise on a service the env registry does
not know, so an undeclared gate fails the scenario at runtime — in a
swarm round that costs a two-hour job to learn a typo. The tolerant
``safeSkipUnlessEnabled`` / ``safeIsEnabled`` pair exists precisely to
read an unknown service as disabled, so gates made through them are
exempt.

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

Without this guard a role can declare ``SSO_SERVICE_ENABLED`` in its
env template, run with ``SSO_SERVICE_ENABLED=false``, and still have
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
_SHARED_HARNESS_DIR = "roles/test-e2e-playwright/files"
_PERSONA_RUNNERS: tuple[str, ...] = ("runGuestFlow", "runBiberFlow", "runAdminFlow")

_LOCAL_REQUIRE_RE = re.compile(r"""require\(\s*['"]\./([A-Za-z0-9_.-]+)['"]\s*\)""")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

_FLAG_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)_SERVICE_ENABLED\s*=")
_HELPER_CALL_RE = re.compile(
    r"\b(?:requireService|skipUnlessServiceEnabled|skipUnlessServiceDisabled|isServiceEnabled|"
    r"isServiceDisabledReason|safeSkipUnlessEnabled|safeIsEnabled)\s*\(\s*['\"]([^'\"]+)['\"]"
)
_STRICT_HELPER_CALL_RE = re.compile(
    r"\b(?:requireService|skipUnlessServiceEnabled|skipUnlessServiceDisabled|isServiceEnabled|"
    r"isServiceDisabledReason)\s*\(\s*['\"]([^'\"]+)['\"]"
)
_LINE_COMMENT_RE = re.compile(r"^\s*//.*$", re.MULTILINE)


def _js_files_under(spec_dir: Path) -> list[str]:
    """Return every ``.js`` path beneath one role's playwright directory.

    Args:
        spec_dir: the role's ``files/playwright`` directory.
    """
    prefix = f"{spec_dir}/"
    return sorted(
        path
        for path in iter_project_files(extensions=(".js",))
        if path.startswith(prefix)
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

    A `require("./<name>")` that resolves to a module of the shared
    harness rather than to a sibling counts the same way: the harness is
    staged flat into the role's own test directory, so a gate declared
    there is the very call the spec makes. Its block comments are stripped
    first: `service-gating.js` documents its own contract with literal
    `isServiceEnabled("sso")` / `isServiceDisabledReason("email")` examples,
    and crediting those would exempt EMAIL, SSO and OICD for every role that
    requires it.
    """
    spec_dir_texts = [read_text(path) for path in _js_files_under(spec_path.parent)]
    for name in {m for text in spec_dir_texts for m in _LOCAL_REQUIRE_RE.findall(text)}:
        harness_path = (
            PROJECT_ROOT / _SHARED_HARNESS_DIR / f"{name.removesuffix('.js')}.js"
        )
        if harness_path.is_file():
            spec_dir_texts.append(
                _BLOCK_COMMENT_RE.sub("", read_text(str(harness_path)))
            )
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


def _strict_gates_in_role_specs(spec_path: Path) -> dict[str, set[str]]:
    """``{env_key_root: {spec file names}}`` for every strict gate made by
    the role's OWN playwright files.

    The shared harness and the personas directory are deliberately not
    credited here: they gate services of whichever role stages them, so
    their calls say nothing about what this role's env template must
    declare. Comments are stripped first, since several specs quote a
    helper call in their header to describe the scenario.
    """
    gates: dict[str, set[str]] = {}
    for js_path in _js_files_under(spec_path.parent):
        text = _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", read_text(js_path)))
        for name in _STRICT_HELPER_CALL_RE.findall(text):
            gates.setdefault(_service_to_env_key_root(name), set()).add(
                js_path.rsplit("/", 1)[-1]
            )
    return gates


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

    def test_every_strict_gate_has_a_declared_flag(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            env_path = role_dir / _ENV_TEMPLATE_REL
            spec_path = role_dir / _SPEC_FILE_REL
            if not env_path.is_file() or not spec_path.is_file():
                continue

            declared = {root for _, root in _flag_lines_in_env(env_path)}

            for root, files in sorted(_strict_gates_in_role_specs(spec_path).items()):
                if root in declared:
                    continue

                offenders.append(
                    f"{role_dir.name}: {', '.join(sorted(files))} gates "
                    f'"{root.lower()}" through a strict helper, but '
                    f"{_ENV_TEMPLATE_REL} declares no "
                    f"`{root}_SERVICE_ENABLED=`. The helper raises on an "
                    f"unknown service, so the scenario fails at runtime. "
                    f"Declare the flag, correct the service name, or use "
                    f"`safeSkipUnlessEnabled` when the service is "
                    f"legitimately absent from the registry."
                )

        if offenders:
            self.fail(
                "Playwright gates on services no env template declares:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
