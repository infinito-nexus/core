"""Lint: every `web-app-*` role's `files/playwright/playwright.spec.js` MUST
contain the three persona scenarios named per the SPOT contract in
[playwright.specs.js.md](../../../../../../docs/contributing/artefact/files/role/playwright.specs.js.md):

    test("guest: <flow>", …)
    test("biber: <flow>", …)
    test("administrator: <flow>", …)

The `<persona>` token MUST appear at the very start of the test
title so the Playwright reporter groups runs by persona without
further parsing.

Suppression
-----------

Three independent opt-outs are recognised; each MAY suppress one or
more personas:

* **Explicit role-contract opt-out** — a
  `PERSONA_<PERSONA>_BLOCKED=true` line in the role's
  `templates/playwright.env.j2` declares that the persona has no
  runnable journey and the spec body legitimately omits it. The
  persona-helper hard-fails any spec that runs the runner without
  the flag set.
* **Auth-less collapse exception (SPOT contract)** — a role that
  ships no `templates/playwright.env.j2` at all is auth-less by
  construction (no inventory entry surfaces it as an end-user
  surface) and MAY collapse all three personas into a single
  baseline reachability scenario in the spec.
* **Web-svc-* roles** are not subject to the persona contract per
  the SPOT contract; this lint only checks `web-app-*` roles.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

_REQUIRED_PERSONAS: tuple[str, ...] = ("guest", "biber", "administrator")
_TEST_TITLE_RE = re.compile(
    r"""^\s*test\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_BLOCKED_FLAG_RE_TPL = r"^\s*PERSONA_{persona}_BLOCKED\s*=\s*true\b"


def _persona_titles_in_spec(spec_text: str) -> set[str]:
    """Return the set of persona tokens that appear at the start of
    a `test("…")` title, e.g. `{"guest", "biber"}`."""
    found: set[str] = set()
    for title in _TEST_TITLE_RE.findall(spec_text):
        for persona in _REQUIRED_PERSONAS:
            if title.startswith(f"{persona}:"):
                found.add(persona)
    return found


def _personas_blocked_in_env(env_text: str) -> set[str]:
    blocked: set[str] = set()
    for persona in _REQUIRED_PERSONAS:
        pattern = _BLOCKED_FLAG_RE_TPL.format(persona=persona.upper())
        if re.search(pattern, env_text, re.MULTILINE):
            blocked.add(persona)
    return blocked


class TestPersonaNaming(unittest.TestCase):
    def test_every_web_app_role_carries_the_three_personas(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            if not role_name.startswith("web-app-"):
                continue
            spec_path = role_dir / ROLE_FILE_PLAYWRIGHT_SPEC
            if not spec_path.is_file():
                continue
            env_path = role_dir / "templates" / "playwright.env.j2"
            # Auth-less collapse exception: roles without a Playwright
            # env template are not orchestrated by test-e2e-playwright
            # and the persona contract does not apply.
            if not env_path.is_file():
                continue

            # Roles may keep the spec monolithic, or split each `test(...)`
            # block into its own `test-<scenario>.js` companion module that
            # `playwright.spec.js` `require()`s. Aggregate persona titles
            # across all sibling `.js` files in the role's playwright dir
            # so the lint stays correct for both layouts.
            seen: set[str] = set()
            for js_path in sorted(spec_path.parent.glob("*.js")):
                seen |= _persona_titles_in_spec(read_text(str(js_path)))
            blocked = _personas_blocked_in_env(read_text(str(env_path)))
            missing = set(_REQUIRED_PERSONAS) - seen - blocked
            if missing:
                missing_sorted = sorted(missing)
                offenders.append(
                    f"{role_name}: {ROLE_FILE_PLAYWRIGHT_SPEC} has no "
                    f'`test("<persona>: …")` for personas {missing_sorted}; '
                    f"add the scenario(s) using `runGuestFlow` / "
                    f"`runBiberFlow` / `runAdminFlow` from `./personas`, OR "
                    f"declare `PERSONA_{{PERSONA}}_BLOCKED=true` in "
                    f"templates/playwright.env.j2 with a documented "
                    f"rationale in the role's README / TODO."
                )

        if offenders:
            self.fail(
                "Persona-naming contract violations:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
