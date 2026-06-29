"""Lint: persona helpers MUST fail loudly on un-executable journeys
AND deny-check helpers MUST validate response body
content on a 200.

Two independent checks, both backed by source-shape regex against the
persona-helper tree under
``roles/test-e2e-playwright/files/personas/``.

Rule 11 (strict skip): every ``test.skip(...)`` call inside the
persona-flow runners (``biber.js`` / ``admin.js`` / ``guest.js``) MUST
sit in a branch guarded by one of these allowed conditions:

* an explicit env opt-out: ``PERSONA_BIBER_BLOCKED`` /
  ``PERSONA_ADMINISTRATOR_BLOCKED`` / ``PERSONA_GUEST_BLOCKED``
  (matched against ``process.env.<FLAG>``),
* an auth-less persona-collapse case: a guard that AND-combines
  emptiness of ``canonicalDomain`` with ``appBaseUrl``
  (persona-collapse exception),
* a service-gate skip via ``safeSkipUnlessEnabled(...)`` /
  ``skipUnlessServiceEnabled(...)``: that helper itself owns the
  skip-on-disabled-service contract.

The check walks backwards from each ``test.skip(`` occurrence to the
nearest enclosing ``if (`` and asserts that condition contains an
allowed token.

Rule 12 (200-body content check): in every deny-check helper that
handles ``status === 200`` (under
``roles/test-e2e-playwright/files/personas/utils/prometheus.js`` and
``…/matomo.js``), the 200-branch MUST contain BOTH:

* a body read (``await probe.text()`` / ``await probe.body()``), AND
* a body-content assertion (a ``test()`` of the body / a
  ``.test(body)`` / ``.includes(`` against role-specific markers).

The 200-branch is delimited by the matching closing brace of the
``if`` / ``else if`` that introduced ``status === 200``.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

PERSONAS_DIR = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "personas"
_FLOW_FILES: tuple[str, ...] = ("biber.js", "admin.js", "guest.js")
_DENY_HELPER_FILES: tuple[str, ...] = ("prometheus.js", "matomo.js")

_TEST_SKIP_RE = re.compile(r"\btest\.skip\s*\(", re.MULTILINE)
_STATUS_200_RE = re.compile(r"\b(?:status\s*===\s*200|=== 200|status\s*==\s*200)\b")

_ALLOWED_SKIP_GUARDS: tuple[str, ...] = (
    "PERSONA_BIBER_BLOCKED",
    "PERSONA_ADMINISTRATOR_BLOCKED",
    "PERSONA_GUEST_BLOCKED",
    # Auth-less persona-collapse exception:
    "!canonicalDomain",
    "!appBaseUrl",
    # Service-gate skip — the helper itself owns the contract:
    "safeSkipUnlessEnabled",
    "skipUnlessServiceEnabled",
)

_BODY_READ_RE = re.compile(r"\bawait\s+probe\.(?:text|body)\s*\(\s*\)")
_BODY_ASSERT_RE = re.compile(
    r"\.test\s*\(\s*body\s*\)|\bbody\.(?:includes|match|search)\s*\(|"
    r"\bisMatomoLogin\b|\bisPrometheus\b|\bshowsAdminUi\b"
)


def _balanced_block_end(text: str, open_brace_idx: int) -> int | None:
    depth = 0
    i = open_brace_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _enclosing_if_condition(text: str, idx: int) -> str | None:
    """Walk backwards from ``idx`` to the nearest enclosing ``if (``
    at the same brace depth and return its full condition string."""
    depth = 0
    i = idx - 1
    while i >= 0:
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                # We found the open of the enclosing block. Walk back
                # over whitespace and capture the `if (...)` head.
                j = i - 1
                while j >= 0 and text[j] in " \t\n\r":
                    j -= 1
                if j < 0 or text[j] != ")":
                    return None
                # Match parens backwards to extract the condition.
                paren_depth = 1
                k = j - 1
                while k >= 0 and paren_depth > 0:
                    if text[k] == ")":
                        paren_depth += 1
                    elif text[k] == "(":
                        paren_depth -= 1
                    k -= 1
                if paren_depth != 0:
                    return None
                cond_start = k + 2
                cond_end = j
                # Verify the keyword before the `(` is `if`.
                pre = text[: k + 1].rstrip()
                if not pre.endswith("if"):
                    return None
                return text[cond_start:cond_end]
            depth -= 1
        i -= 1
    return None


class TestPersonaStrictMode(unittest.TestCase):
    def test_persona_skips_only_via_explicit_opt_out(self):
        offenders: list[str] = []
        for fname in _FLOW_FILES:
            path = PERSONAS_DIR / fname
            if not path.is_file():
                continue
            text = read_text(str(path))
            for m in _TEST_SKIP_RE.finditer(text):
                cond = _enclosing_if_condition(text, m.start())
                if cond is None:
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)} line "
                        f"{text[: m.start()].count(chr(10)) + 1}: "
                        f"`test.skip(...)` is NOT inside an `if (...)` "
                        f"branch. Persona skips MUST be guarded by an "
                        f"explicit env opt-out (PERSONA_<X>_BLOCKED) or "
                        f"the auth-less persona-collapse condition."
                    )
                    continue
                if not any(tok in cond for tok in _ALLOWED_SKIP_GUARDS):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)} line "
                        f"{text[: m.start()].count(chr(10)) + 1}: "
                        f"`test.skip(...)` guard `{cond.strip()}` does "
                        f"NOT reference an allowed opt-out token. "
                        f"Allowed: {', '.join(_ALLOWED_SKIP_GUARDS)}. "
                        f"Per the runtime contract, auto-detection "
                        f"skips are forbidden — only explicit env opt-outs "
                        f"or the auth-less collapse case may skip cleanly."
                    )

        if offenders:
            self.fail(
                "Persona-helper skip violations:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_deny_helpers_validate_body_on_200(self):
        offenders: list[str] = []
        utils_dir = PERSONAS_DIR / "utils"
        for fname in _DENY_HELPER_FILES:
            path = utils_dir / fname
            if not path.is_file():
                continue
            text = read_text(str(path))
            for m in _STATUS_200_RE.finditer(text):
                # Find the opening `{` of the branch this `=== 200`
                # introduces. The branch may be `if (status === 200) {`
                # — walk forward to the next `{`.
                brace_idx = text.find("{", m.end())
                if brace_idx < 0:
                    continue
                end_idx = _balanced_block_end(text, brace_idx)
                if end_idx is None:
                    continue
                block = text[brace_idx + 1 : end_idx]
                if not _BODY_READ_RE.search(block):
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)} line {line_no}: "
                        f"`status === 200` branch does NOT read the body "
                        f"(no `await probe.text()` / `await probe.body()`). "
                        f"A 200-hop is only acceptable "
                        f"after validating the body matches role-specific "
                        f"markers."
                    )
                    continue
                if not _BODY_ASSERT_RE.search(block):
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)} line {line_no}: "
                        f"`status === 200` branch reads the body but does "
                        f"NOT assert role-specific markers (no "
                        f"`<re>.test(body)` / `body.includes(...)` / "
                        f"`isMatomoLogin` / `isPrometheus` / `showsAdminUi`). "
                        f"An unchecked 200 with the "
                        f"wrong body is a misconfigured proxy / "
                        f"denial-as-200 surface and MUST fail loudly."
                    )

        if offenders:
            self.fail(
                "Deny-helper 200-body-content violations:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
