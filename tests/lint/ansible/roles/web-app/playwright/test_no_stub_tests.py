"""Lint: every `test()` body in `roles/<role>/files/playwright/playwright.spec.js`
MUST simulate a real user flow.

Stub bodies are forbidden by the spec contract in
[playwright.specs.js.md](../../../../../../docs/contributing/artefact/files/role/playwright.specs.js.md):
the persona scenarios MUST drive an actual flow (dashboard click, OIDC
login, asset assertion, …) and assert on a user-visible state, not just
mark themselves present.

A test body is rejected as a stub when ALL of the following hold:

* it contains zero `expect(`, `assert`, or `await page.` calls;
* AND its only statements are: `skipUnlessServiceEnabled(...)`,
  comments, blank lines, or no statements at all;
* AND it contains no helper invocation that drives a real flow
  (`runBiberFlow`, `runAdminFlow`, `requireService`,
  `await request.`, …).

A test body is also rejected when it carries an explicit `TODO` or
`STUB` marker inside the body (case-insensitive). The rollout's
intent is real flows, not deferred work.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

# Match `test("title", ...)` or `test('title', ...)` and capture the
# title and the body block. Body capture is intentionally greedy across
# the body-arrow function. The matcher is conservative; nested braces
# inside the body are handled by `_extract_body_balanced`.
_TEST_HEAD_RE = re.compile(
    r"""\btest\s*\(\s*['"]([^'"]+)['"]\s*,\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{""",
    re.MULTILINE,
)

# Keywords that count as "real flow" content — at least one MUST appear
# in any non-stub test body. The list is permissive on purpose: any
# `expect()` / `assert()` / `await <fn>()` call counts as real work,
# because role-local specs use a wide variety of helper functions
# (`signInViaBbbOidc`, `bbbLogout`, `wpAdminLoginViaOidc`, …) and the
# lint MUST accept them all without an allowlist update per role.
_REAL_FLOW_TOKENS = (
    "expect(",
    "assert(",
    "await ",
    "requireService(",
    "isServiceEnabled(",
    "isServiceDisabledReason(",
)

# Keywords that mark a body as a deferred stub. Matched as standalone
# words (`\bTODO\b`) so substrings like ``masTODOn`` in a regex
# alternation or an app name do NOT trip the lint.
_STUB_MARKERS = ("TODO", "STUB", "FIXME", "XXX")
_STUB_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(_STUB_MARKERS) + r")\b",
    re.IGNORECASE,
)

# Tautological self-check pattern. A body whose only meaningful work is
# `skipUnlessServiceEnabled("X"); expect(isServiceEnabled("X")).toBe(true)`
# proves nothing the gate itself didn't already prove (the gate would
# have skipped the test if `isServiceEnabled` returned false). The
# "contract: <svc> gate is wired" stubs that earlier batch updates wrote
# match this shape; the lint catches the body shape so renaming the
# title is not enough.
_TAUTOLOGY_RE = re.compile(
    r"\bskipUnlessServiceEnabled\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;\s*"
    r"expect\s*\(\s*isServiceEnabled\s*\(\s*['\"]\1['\"]\s*\)\s*\)\s*"
    r"\.\s*toBe\s*\(\s*(?:true|false)\s*\)\s*;?",
)

# Banned-title pattern: even if the body is later padded with a
# meaningful interaction, a test titled "contract: <svc> gate is wired"
# is reserved for the historical stub shape and MUST NOT be reintroduced.
# Future spec authors who legitimately want a per-gate assertion MUST
# pick a descriptive title (e.g. "matomo: tracking snippet present on
# canonical page") that names the actual user-visible signal.
_BANNED_TITLE_RE = re.compile(
    r"^\s*contract:\s*[a-z0-9_-]+\s+gate\s+is\s+wired\s*$", re.IGNORECASE
)


def _extract_body_balanced(text: str, open_brace_idx: int) -> str | None:
    """Return the substring from open_brace_idx (a `{`) to the matching
    `}` honoring nested braces. Returns None if unbalanced."""
    depth = 0
    i = open_brace_idx
    n = len(text)
    in_str = None
    in_template = False
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if in_template:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_template = False
            elif ch == "$" and nxt == "{":
                # template-string interpolation: treat braces normally
                # by entering depth tracking
                pass
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ("'", '"'):
            in_str = ch
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : i]
        i += 1
    return None


def _strip_body(body: str) -> str:
    """Remove comments and whitespace; return the meaningful body text
    used to decide stub-ness."""
    # Strip block comments
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    # Strip line comments
    body = re.sub(r"//[^\n]*", "", body)
    return body.strip()


def _body_contains_real_flow(body: str) -> bool:
    return any(token in body for token in _REAL_FLOW_TOKENS)


def _body_contains_stub_marker(body: str) -> bool:
    return _STUB_MARKER_RE.search(body) is not None


def _is_persona_or_contract_test(title: str) -> bool:
    """Return True for test titles that this lint specifically targets:
    persona scenarios and contract tests. Other tests are scoped by their
    own contracts elsewhere; this lint does not retroactively review
    every legacy test."""
    lower = title.lower()
    return (
        lower.startswith(("biber:", "administrator:", "contract:"))
        or "persona" in lower
    )


class TestNoStubTests(unittest.TestCase):
    def test_persona_and_contract_tests_simulate_real_flows(self):
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            spec = role_dir / ROLE_FILE_PLAYWRIGHT_SPEC
            if not spec.is_file():
                continue
            text = read_text(str(spec))
            for m in _TEST_HEAD_RE.finditer(text):
                title = m.group(1)
                if not _is_persona_or_contract_test(title):
                    continue
                # Find the `{` that opens the body.
                open_idx = text.find("{", m.end() - 1)
                if open_idx < 0:
                    continue
                body = _extract_body_balanced(text, open_idx)
                if body is None:
                    continue

                if _BANNED_TITLE_RE.search(title):
                    offenders.append(
                        f"{role_dir.name}: test {title!r} matches the "
                        f"banned 'contract: <svc> gate is wired' shape; the "
                        f"historical stub it described proves nothing the "
                        f"`skipUnlessServiceEnabled` gate itself doesn't. "
                        f"Drop the test (the persona scenarios already "
                        f"drive the gated flow) or pick a descriptive "
                        f"title that names a user-visible signal."
                    )
                    continue

                if _body_contains_stub_marker(body):
                    offenders.append(
                        f"{role_dir.name}: test {title!r} contains a "
                        f"TODO/STUB/FIXME marker; replace with a real "
                        f"user-flow body per "
                        f"docs/contributing/artefact/files/role/playwright.specs.js.md."
                    )
                    continue

                meaningful = _strip_body(body)
                if not meaningful:
                    offenders.append(
                        f"{role_dir.name}: test {title!r} has an empty "
                        f"body; persona / contract tests MUST drive a real "
                        f"user flow."
                    )
                    continue

                if _TAUTOLOGY_RE.search(meaningful):
                    offenders.append(
                        f"{role_dir.name}: test {title!r} body is a "
                        f"tautological self-check "
                        f"(`skipUnlessServiceEnabled('X'); "
                        f"expect(isServiceEnabled('X')).toBe(true)`). The "
                        f"`expect` cannot fail because the `skip` gate has "
                        f"already enforced the same condition. Replace "
                        f"with a real user-flow assertion or delete the "
                        f"test."
                    )
                    continue

                if not _body_contains_real_flow(body):
                    offenders.append(
                        f"{role_dir.name}: test {title!r} contains no "
                        f"real-flow assertion (no expect / await page.* / "
                        f"runBiberFlow / runAdminFlow / requireService); "
                        f"the body is a stub."
                    )

        if offenders:
            self.fail(
                f"{len(offenders)} stub test(s) detected. Persona and "
                f"contract tests MUST simulate a real user flow per "
                f"docs/contributing/artefact/files/role/playwright.specs.js.md.\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
