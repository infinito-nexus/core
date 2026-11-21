"""Lint guard: Playwright persona scenarios, their service gates and end surfaces.

Every role's Playwright directory is lexed and resolved once per process; each
rule below reads that one parse.

Canonical ``sso`` and ``ldap`` gates
    ``skipUnlessServiceEnabled("<svc>")`` and ``skipUnlessServiceDisabled("<svc>")``
    from ``./service-gating`` skip with the canonical ``<SVC>_SERVICE_ENABLED=<value>``
    reason. A ``test.skip(...)`` or ``test.fixme(...)`` whose condition reads an
    ``sso``, ``ldap`` or ``oidc`` value gates the same service with a free-text reason
    instead. The condition is read directly, through a ``const``/``let``/``var`` or
    object-property binding anywhere in the role's Playwright directory, or from the
    ``if`` that wraps an unconditional skip. ``isSplitRealmOidc()`` stays out of the
    match. Suppress on the skip's line or the line above it with
    ``// nocheck: playwright-sso-ldap-gate -- <reason>``; a marker without a reason of
    at least ten characters grants nothing.

LDAP scenarios are persona tests behind the canonical ``ldap`` gate
    * A test whose title names LDAP reaches ``skipUnlessServiceEnabled("ldap")``, so a
      deploy with ``disable=ldap`` reports it as ``skipped: LDAP_SERVICE_ENABLED=false``.
      A test that asserts the LDAP-off state through ``skipUnlessServiceDisabled("ldap")``
      passes, and so does a test without a persona token that reaches the ``sso`` gate:
      it probes the LDAP side from the SSO journey (login-method toggles, write-through).
    * A test that reaches ``skipUnlessServiceEnabled("ldap")`` and names ``biber`` or
      ``administrator`` in its title starts that title with a persona token
      (``guest:``, ``biber:``, ``administrator:``) or with a ``${...}:`` placeholder
      that renders one, so the reporter groups the LDAP sign-in with that persona.
    * A role whose ``meta/services.yml`` leaves ``ldap.enabled`` other than ``false``
      and whose env template renders persona credentials ships at least one ldap-gated
      test, or its README carries an ``LDAP coverage`` section that states the
      exemption.
    * A role with an ``administrator:`` ldap-gated test but no ``biber:`` one flags the
      biber follow-up in the ``LDAP coverage`` section of its README.

Biber scenarios
    * A ``biber:`` test outside ``runBiberFlow`` gates on ``sso`` or ``ldap`` like the
      ``administrator:`` tests of its module.
    * One ``biber:`` test of a role runs ``runBiberFlow`` or ends on a surface the
      biber session renders, and no lone biber session expects an admin-only element.
    * A role whose ``meta/rbac.yml`` offers biber an application role pins that role
      in a ``biber:`` assertion, or flags the bare check in a README
      ``Biber coverage`` section.

A gate counts when the test calls it directly, through a function declared in the
role's Playwright directory, or through a ``test.beforeEach`` / ``test.beforeAll``
hook of its file or of an enclosing ``test.describe``.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text, repository_files
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_RBAC,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_README,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

RULE = "playwright-sso-ldap-gate"
_MIN_REASON = 10
_TOKENS = frozenset({"ldap", "oidc", "sso"})
_TOPOLOGY_PREDICATE_RE = re.compile(r"\bisSplitRealmOidc\s*\(\s*\)")
_PLAYWRIGHT_DIR = "/files/playwright/"

_SKIP_RE = re.compile(
    r"(?<![\w$])(?:test\.info\(\)|testInfo|test)\.(?:skip|fixme)\s*\("
)
_IF_RE = re.compile(r"\bif\s*\(")
_DECL_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=(?![=>])")
_PROP_RE = re.compile(r"^[^\S\n]*([A-Za-z_$][\w$]*)\s*:(?!:)", re.MULTILINE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_PART_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
_REGEX_PRECEDERS = frozenset("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = frozenset({"return", "typeof", "case", "in", "of", "delete", "void"})
_CONTINUES_BEFORE = tuple("=([{,?:|&+-*/!>")
_CONTINUES_AFTER = tuple(".?:|&+-*/")
_LOOKBACK = 600
_MAX_DEPTH = 6

_TEST_RE = re.compile(r"(?<![\w$.])test\s*\(")
_DESCRIBE_RE = re.compile(r"(?<![\w$.])test\.describe(?:\.\w+)*\s*\(")
_HOOK_RE = re.compile(r"(?<![\w$.])test\.(?:beforeEach|beforeAll)\s*\(")
_GATE_RE = re.compile(
    r"\b(skipUnlessServiceEnabled|skipUnlessServiceDisabled|requireService|"
    r"safeSkipUnlessEnabled)\s*\(\s*['\"]([^'\"]+)['\"]"
)
_FUNCTION_DECL_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")
_FUNCTION_BIND_RE = re.compile(
    r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?"
    r"(?:function\b[^{]*|(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>\s*)\{"
)
_CALL_RE = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*\(")
_REFERENCE_RE = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)")
_PERSONA_TITLE_RE = re.compile(r"^(?:guest|biber|administrator):|^\$\{[^}]*\}:")
_SIGNED_IN_PERSONA_RE = re.compile(r"\b(?:biber|administrator)\b", re.IGNORECASE)
_BIBER_RE = re.compile(r"\bbiber\b")
_ADMINISTRATOR_RE = re.compile(r"\badministrator\b", re.IGNORECASE)
_ENABLED = "enabled"
_DISABLED = "disabled"
_GATE_KIND = {
    "skipUnlessServiceEnabled": _ENABLED,
    "requireService": _ENABLED,
    "safeSkipUnlessEnabled": _ENABLED,
    "skipUnlessServiceDisabled": _DISABLED,
}
_ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_PERSONA_CREDENTIAL_RE = re.compile(r"^\s*(?:ADMIN|BIBER)_USERNAME\s*=", re.MULTILINE)
_COVERAGE_SECTION_RE = re.compile(
    r"^##+[ \t]+LDAP coverage[ \t]*$(.*?)(?=^#|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)

_SIGN_IN_SERVICES = frozenset({"sso", "ldap"})
_BIBER_FLOW = "runBiberFlow"

_EXPECT_RE = re.compile(r"(?<![\w$.])expect\s*(?:\.\s*(?:poll|soft)\s*)?\(")
_MATCHER_RE = re.compile(r"\s*(\.\s*not)?\s*\.\s*(to\w+)\s*\(")
_WEB_FIRST = frozenset(
    {
        "toBeAttached",
        "toBeVisible",
        "toContainText",
        "toHaveText",
        "toHaveTitle",
        "toHaveURL",
    }
)
_COUNT = "toHaveCount"
_VALUE_MATCHERS = frozenset(
    {"toBe", "toContain", "toEqual", "toMatch", "toStrictEqual"}
)
_PAGE_READ_RE = re.compile(
    r"\.\s*(?:url|title|innerText|textContent|allInnerTexts|allTextContents)\s*\("
)
_ADMIN_RE = re.compile(
    r"(?i)(?<![\w$-])(?:wp-)?admin(?:istration|istrator|s)?(?![\w$]|-bar\b)"
)
_SECOND_SESSION_RE = re.compile(
    r"\bnew(?:Context|Page)\s*\(|\badmin\w*(?:Page|Context)\b|"
    r"\badmin(?:Username|Password)\b|\bADMIN_(?:USERNAME|PASSWORD)\b"
)
_ADMIN_GRANT_RE = re.compile(
    r"(?i)administrator\w*_?group|groups\.administrator|[-/]administrator\b|site-?owner"
)

_UNMAPPED_ROLES = frozenset({"administrator", "mcp"})
_ABSENCE_MATCHERS = frozenset({"toBeFalsy", "toBeHidden", "toBeNull", "toBeUndefined"})
_EQUALITY_MATCHERS = frozenset({"toBe", "toEqual", "toStrictEqual"})
_ABSENT_VALUES = frozenset({"0", "false", "null", "undefined"})
_REFUSAL_RE = re.compile(r"\b40[134]\b")
_ADMIN_SCOPE_RE = re.compile(
    r"(?i)(?<![\w$-])(?:wp-)?admin(?:istration|istrator|s)?(?:_[a-z_]+)?(?![a-z$]|-bar\b)"
)
_BIBER_SECTION_RE = re.compile(
    r"^##+[ \t]+Biber coverage[ \t]*$(.*?)(?=^#|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Violation:
    file: str
    line_no: int
    condition: str


@dataclass(frozen=True, order=True)
class Scenario:
    file: str
    line_no: int
    title: str
    gates: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class PersonaTest:
    scenario: Scenario
    code: str


@dataclass(frozen=True)
class Assertion:
    subject: str
    negated: bool
    matcher: str
    expected: str


def _string_end(text: str, start: int) -> int:
    quote = text[start]
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote or (quote != "`" and ch == "\n"):
            return i + 1
        i += 1
    return len(text)


def _regex_end(text: str, start: int) -> int:
    i = start + 1
    in_class = False
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n":
            return i
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "/":
            i += 1
            while i < len(text) and text[i].isalpha():
                i += 1
            return i
        i += 1
    return len(text)


def _starts_regex(text: str, slash: int) -> bool:
    j = slash - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0 or text[j] in _REGEX_PRECEDERS:
        return True
    if text[j].isalnum() or text[j] in "_$":
        k = j
        while k >= 0 and (text[k].isalnum() or text[k] in "_$"):
            k -= 1
        return text[k + 1 : j + 1] in _REGEX_KEYWORDS
    return False


def _blank(chars: list[str], start: int, end: int) -> None:
    for i in range(start, end):
        if chars[i] != "\n":
            chars[i] = " "


@cache
def _lex(text: str) -> tuple[str, str]:
    """Split JavaScript source into two offset-preserving views, once per text.

    Args:
        text: the JavaScript source.

    Returns:
        ``(code, skeleton)``: ``code`` blanks comments; ``skeleton`` additionally
        blanks the contents of string, template and regex literals.
    """
    code = list(text)
    skeleton = list(text)
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            _blank(code, i, end)
            _blank(skeleton, i, end)
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            _blank(code, i, end)
            _blank(skeleton, i, end)
            i = end
            continue
        ch = text[i]
        if ch in "\"'`":
            end = _string_end(text, i)
            _blank(skeleton, i + 1, max(i + 1, end - 1))
            i = end
            continue
        if ch == "/" and _starts_regex(text, i):
            end = _regex_end(text, i)
            _blank(skeleton, i + 1, max(i + 1, end - 1))
            i = end
            continue
        i += 1
    return "".join(code), "".join(skeleton)


def _close_of(skeleton: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(skeleton)):
        ch = skeleton[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _first_argument(skeleton: str, open_idx: int, close_idx: int) -> tuple[int, int]:
    depth = 0
    for i in range(open_idx + 1, close_idx):
        ch = skeleton[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return open_idx + 1, i
    return open_idx + 1, close_idx


def _expression_end(skeleton: str, start: int) -> int:
    depth = 0
    for i in range(start, len(skeleton)):
        ch = skeleton[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0 and ch in ";,":
            return i
        elif depth == 0 and ch == "\n":
            before = skeleton[start:i].rstrip()
            after = skeleton[i:].lstrip()
            if (
                before
                and not before.endswith(_CONTINUES_BEFORE)
                and not after.startswith(_CONTINUES_AFTER)
            ):
                return i
    return len(skeleton)


def _names_token(fragment: str) -> bool:
    return any(
        part.lower() in _TOKENS
        for word in _WORD_RE.findall(_TOPOLOGY_PREDICATE_RE.sub(" ", fragment))
        for part in _PART_RE.findall(word)
    )


def _resolvable_names(skeleton_fragment: str) -> set[str]:
    return {
        match.group(0)
        for match in _IDENT_RE.finditer(skeleton_fragment)
        if not skeleton_fragment[match.end() :].lstrip().startswith(".")
    }


def bindings_in(texts: Iterable[str]) -> dict[str, list[tuple[str, str]]]:
    """Collect every ``const``/``let``/``var`` and object-property binding.

    Args:
        texts: the JavaScript sources of one role's Playwright directory.

    Returns:
        Binding name mapped to the ``(code, skeleton)`` slices of each expression
        bound to it.
    """
    bindings: dict[str, list[tuple[str, str]]] = {}
    for text in texts:
        code, skeleton = _lex(text)
        for pattern in (_DECL_RE, _PROP_RE):
            for match in pattern.finditer(skeleton):
                start = match.end()
                end = _expression_end(skeleton, start)
                bindings.setdefault(match.group(1), []).append(
                    (code[start:end], skeleton[start:end])
                )
    return bindings


def _reads_sso_or_ldap(
    code_fragment: str,
    skeleton_fragment: str,
    bindings: Mapping[str, list[tuple[str, str]]],
    seen: set[str],
    depth: int,
) -> bool:
    if _names_token(code_fragment):
        return True
    if depth >= _MAX_DEPTH:
        return False
    for name in _resolvable_names(skeleton_fragment) - seen:
        seen.add(name)
        for bound_code, bound_skeleton in bindings.get(name, ()):
            if _reads_sso_or_ldap(
                bound_code, bound_skeleton, bindings, seen, depth + 1
            ):
                return True
    return False


def _wrapping_if(skeleton: str, call_start: int) -> tuple[int, int] | None:
    window_start = max(0, call_start - _LOOKBACK)
    for match in reversed(list(_IF_RE.finditer(skeleton, window_start, call_start))):
        open_idx = match.end() - 1
        close_idx = _close_of(skeleton, open_idx)
        if close_idx == -1 or close_idx >= call_start:
            continue
        if re.fullmatch(r"\s*\{?\s*", skeleton[close_idx + 1 : call_start]):
            return open_idx + 1, close_idx
        return None
    return None


def _has_reasoned_marker(lines: list[str], line_no: int) -> bool:
    candidates = [line_no - 1]
    above = line_no - 2
    while above >= 0 and not lines[above].strip():
        above -= 1
    if above >= 0:
        candidates.append(above)
    for idx in candidates:
        if idx >= len(lines) or not line_has_rule(lines[idx], RULE):
            continue
        reason = lines[idx].split(RULE, 1)[1].strip(" \t-:")
        if len(reason) >= _MIN_REASON:
            return True
    return False


def findings_in(
    text: str, bindings: Mapping[str, list[tuple[str, str]]]
) -> list[tuple[int, str]]:
    """Report every skip gate in ``text`` that reads an sso, ldap or oidc value.

    Args:
        text: the JavaScript source of one spec module.
        bindings: :func:`bindings_in` over the role's Playwright directory.

    Returns:
        ``(line_no, condition)`` per unsuppressed gate, 1-based.
    """
    code, skeleton = _lex(text)
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    for match in _SKIP_RE.finditer(skeleton):
        open_idx = match.end() - 1
        close_idx = _close_of(skeleton, open_idx)
        if close_idx == -1:
            continue
        arg_start, arg_end = _first_argument(skeleton, open_idx, close_idx)
        first = skeleton[arg_start:arg_end].strip()
        if first and first[0] in "\"'`":
            continue
        marker_lines = [text.count("\n", 0, match.start()) + 1]
        if first in ("", "true"):
            wrapper = _wrapping_if(skeleton, match.start())
            if wrapper is None:
                continue
            arg_start, arg_end = wrapper
            marker_lines.append(text.count("\n", 0, arg_start) + 1)
        condition_code = code[arg_start:arg_end]
        if not _reads_sso_or_ldap(
            condition_code, skeleton[arg_start:arg_end], bindings, set(), 0
        ):
            continue
        if any(_has_reasoned_marker(lines, n) for n in marker_lines):
            continue
        found.append((marker_lines[0], " ".join(condition_code.split())))
    return found


def _playwright_root(rel: str) -> str:
    head, _, _ = rel.partition(_PLAYWRIGHT_DIR)
    return head + _PLAYWRIGHT_DIR


def _scan_targets() -> dict[str, list[str]]:
    roots: dict[str, list[str]] = {}
    for rel in repository_files(untracked=True):
        if (
            not rel.startswith("roles/")
            or not rel.endswith(".js")
            or _PLAYWRIGHT_DIR not in rel
        ):
            continue
        if not (PROJECT_ROOT / rel).is_file():
            continue
        roots.setdefault(_playwright_root(rel), []).append(rel)
    return roots


def _body_after(skeleton: str, start: int) -> tuple[int, int] | None:
    brace = skeleton.find("{", start)
    if brace == -1:
        return None
    close = _close_of(skeleton, brace)
    return None if close == -1 else (brace, close)


def _functions_of(code: str, skeleton: str) -> dict[str, list[str]]:
    functions: dict[str, list[str]] = {}
    for match in _FUNCTION_DECL_RE.finditer(skeleton):
        params_close = _close_of(skeleton, match.end() - 1)
        span = None if params_close == -1 else _body_after(skeleton, params_close)
        if span:
            functions.setdefault(match.group(1), []).append(code[span[0] : span[1]])
    for match in _FUNCTION_BIND_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close != -1:
            functions.setdefault(match.group(1), []).append(
                code[match.end() - 1 : close]
            )
    return functions


def helper_functions_in(texts: Iterable[str]) -> dict[str, list[str]]:
    """Collect the functions of the helper modules in a role's Playwright directory.

    A module that declares no ``test(...)`` is a helper module (``_shared.js``,
    ``sign-in.js``); functions of test modules stay local to their own module.

    Args:
        texts: the JavaScript sources of one role's Playwright directory.

    Returns:
        Function name mapped to the comment-free code of each body declared for it.
    """
    functions: dict[str, list[str]] = {}
    for text in texts:
        code, skeleton = _lex(text)
        if _TEST_RE.search(skeleton):
            continue
        for name, bodies in _functions_of(code, skeleton).items():
            functions.setdefault(name, []).extend(bodies)
    return functions


def _gates_in(
    code_fragment: str,
    functions: Mapping[str, list[str]],
    seen: set[str],
    depth: int,
    names_re: re.Pattern[str],
) -> set[tuple[str, str]]:
    gates = {
        (_GATE_KIND[helper], service.lower())
        for helper, service in _GATE_RE.findall(code_fragment)
    }
    if depth >= _MAX_DEPTH:
        return gates
    for name in set(names_re.findall(code_fragment)) - seen:
        seen.add(name)
        for body in functions.get(name, ()):
            gates |= _gates_in(body, functions, seen, depth + 1, _CALL_RE)
    return gates


def _innermost(spans: list[tuple[int, int]], index: int) -> tuple[int, int] | None:
    enclosing = [span for span in spans if span[0] < index < span[1]]
    return min(enclosing, key=lambda span: span[1] - span[0], default=None)


def _title_of(code: str, start: int, end: int) -> str:
    title = code[start:end].strip()
    if len(title) >= 2 and title[0] in "\"'`" and title[-1] == title[0]:
        return title[1:-1]
    return title


def scenarios_in(
    rel: str, text: str, helpers: Mapping[str, list[str]]
) -> list[Scenario]:
    """Resolve every ``test(...)`` of one module with the service gates it reaches.

    Args:
        rel: the module's repository-relative path, carried into each scenario.
        text: the JavaScript source of the module.
        helpers: :func:`helper_functions_in` over the role's Playwright directory.

    Returns:
        One :class:`Scenario` per test, its gates as ``(kind, service)`` pairs with
        ``kind`` either ``"enabled"`` or ``"disabled"``.
    """
    code, skeleton = _lex(text)
    functions = {**helpers, **_functions_of(code, skeleton)}
    describes = []
    for match in _DESCRIBE_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close != -1:
            describes.append((match.end() - 1, close))
    hooks = []
    for match in _HOOK_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close != -1:
            gates = _gates_in(
                code[match.end() : close], functions, set(), 0, _REFERENCE_RE
            )
            hooks.append((_innermost(describes, match.start()), gates))
    scenarios: list[Scenario] = []
    for match in _TEST_RE.finditer(skeleton):
        open_idx = match.end() - 1
        close = _close_of(skeleton, open_idx)
        if close == -1:
            continue
        title_start, title_end = _first_argument(skeleton, open_idx, close)
        gates = _gates_in(code[title_end:close], functions, set(), 0, _CALL_RE)
        for scope, hook_gates in hooks:
            if scope is None or scope[0] < match.start() < scope[1]:
                gates |= hook_gates
        scenarios.append(
            Scenario(
                rel,
                text.count("\n", 0, match.start()) + 1,
                _title_of(code, title_start, title_end),
                frozenset(gates),
            )
        )
    return scenarios


def _names_ldap(title: str) -> bool:
    return any(
        part.lower() == "ldap"
        for word in _WORD_RE.findall(title)
        for part in _PART_RE.findall(word)
    )


def ungated_ldap_scenarios(scenarios: Iterable[Scenario]) -> list[Scenario]:
    """Return the tests whose title names LDAP but which skip past the ldap gate.

    Args:
        scenarios: :func:`scenarios_in` results.
    """
    return [
        s
        for s in scenarios
        if _names_ldap(s.title)
        and (_ENABLED, "ldap") not in s.gates
        and (_DISABLED, "ldap") not in s.gates
        and (_PERSONA_TITLE_RE.match(s.title) or (_ENABLED, "sso") not in s.gates)
    ]


def unpersonified_ldap_scenarios(scenarios: Iterable[Scenario]) -> list[Scenario]:
    """Return the ldap-gated tests that name a persona but start with no persona token.

    Args:
        scenarios: :func:`scenarios_in` results.
    """
    return [
        s
        for s in scenarios
        if (_ENABLED, "ldap") in s.gates
        and _SIGNED_IN_PERSONA_RE.search(s.title)
        and not _PERSONA_TITLE_RE.match(s.title)
    ]


def combined_sso_ldap_scenarios(scenarios: Iterable[Scenario]) -> list[Scenario]:
    """Return the tests that reach both the ``sso`` and the ``ldap`` enabled gate.

    Args:
        scenarios: :func:`scenarios_in` results.
    """
    return [
        s
        for s in scenarios
        if (_ENABLED, "sso") in s.gates and (_ENABLED, "ldap") in s.gates
    ]


def declares_ldap(services: object) -> bool:
    """Tell whether a parsed ``meta/services.yml`` leaves ``ldap.enabled`` switchable on.

    Args:
        services: the YAML root of the role's ``meta/services.yml``.
    """
    ldap = services.get("ldap") if isinstance(services, dict) else None
    if not isinstance(ldap, dict) or "enabled" not in ldap:
        return False
    return str(ldap["enabled"]).strip().lower() != "false"


def ldap_coverage_section(readme: str) -> str | None:
    """Return the body of a README's ``LDAP coverage`` section, if it has one.

    Args:
        readme: the role README text.
    """
    match = _COVERAGE_SECTION_RE.search(readme)
    return match.group(1) if match else None


def _ldap_gated(scenarios: Iterable[Scenario]) -> list[Scenario]:
    return [s for s in scenarios if (_ENABLED, "ldap") in s.gates]


def ldap_persona_gap(scenarios: Iterable[Scenario]) -> str | None:
    """Name the persona a role's ldap-gated tests never sign in.

    Args:
        scenarios: :func:`scenarios_in` results of one role.

    Returns:
        ``"biber"`` or ``"administrator"`` when only the other persona has an
        ldap-gated test, ``"persona"`` when no ldap-gated test carries a persona
        token, ``None`` when both are covered or no test is ldap-gated.
    """
    titles = [s.title for s in _ldap_gated(scenarios)]
    if not titles:
        return None
    placeholder = any(t.startswith("${") for t in titles)
    admin = placeholder or any(t.startswith("administrator:") for t in titles)
    biber = placeholder or any(t.startswith("biber:") for t in titles)
    if admin and biber:
        return None
    if admin:
        return "biber"
    return "administrator" if biber else "persona"


def lacks_biber_ldap_scenario(scenarios: Iterable[Scenario]) -> bool:
    """Tell whether a role signs the administrator in over LDAP but never biber.

    Args:
        scenarios: :func:`scenarios_in` results of one role.
    """
    return ldap_persona_gap(scenarios) == "biber"


def _reached(
    fragment: str, functions: Mapping[str, list[str]], seen: set[str], depth: int
) -> list[str]:
    texts = [fragment]
    if depth >= _MAX_DEPTH:
        return texts
    for name in set(_CALL_RE.findall(fragment)) - seen:
        seen.add(name)
        for body in functions.get(name, ()):
            texts.extend(_reached(body, functions, seen, depth + 1))
    return texts


def persona_tests_in(
    rel: str, text: str, helpers: Mapping[str, list[str]]
) -> list[PersonaTest]:
    """Pair every ``test(...)`` of one module with the code its body reaches.

    Args:
        rel: the module's repository-relative path.
        text: the JavaScript source of the module.
        helpers: ``helper_functions_in`` over the role's Playwright directory.

    Returns:
        One :class:`PersonaTest` per test, its ``code`` holding the comment-free
        body plus every function body it calls, up to six calls deep.
    """
    code, skeleton = _lex(text)
    functions = {**helpers, **_functions_of(code, skeleton)}
    bodies: list[str] = []
    for match in _TEST_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close == -1:
            continue
        _, title_end = _first_argument(skeleton, match.end() - 1, close)
        bodies.append("\n".join(_reached(code[title_end:close], functions, set(), 0)))
    return [
        PersonaTest(scenario, body)
        for scenario, body in zip(scenarios_in(rel, text, helpers), bodies, strict=True)
    ]


@cache
def role_persona_tests() -> dict[str, list[PersonaTest]]:
    """Collect the persona tests of every role's Playwright directory.

    Returns:
        Role name mapped to the :class:`PersonaTest` of each of its tests.
    """
    by_role: dict[str, list[PersonaTest]] = defaultdict(list)
    for rels in _scan_targets().values():
        texts = {rel: read_text(str(PROJECT_ROOT / rel)) for rel in rels}
        helpers = helper_functions_in(texts.values())
        for rel, text in texts.items():
            by_role[rel.split("/")[1]].extend(persona_tests_in(rel, text, helpers))
    return by_role


def runs_biber_flow(item: PersonaTest) -> bool:
    """Tell whether a test reaches the shared ``runBiberFlow`` persona.

    Args:
        item: one :func:`persona_tests_in` result.
    """
    return _BIBER_FLOW in _CALL_RE.findall(item.code)


def is_biber_scenario(item: PersonaTest) -> bool:
    """Tell whether a test is a ``biber:`` scenario outside ``runBiberFlow``.

    Args:
        item: one :func:`persona_tests_in` result.
    """
    return item.scenario.title.startswith("biber:") and not runs_biber_flow(item)


def _sign_in_gates(scenario: Scenario) -> frozenset[tuple[str, str]]:
    return frozenset(g for g in scenario.gates if g[1] in _SIGN_IN_SERVICES)


def _enabled(gates: Iterable[tuple[str, str]]) -> set[str]:
    return {service for kind, service in gates if kind == _ENABLED}


def biber_gate_offenders(items: Iterable[PersonaTest]) -> list[tuple[Scenario, str]]:
    """Return the biber scenarios whose sso and ldap gates break the gate rule.

    Args:
        items: :func:`persona_tests_in` results of one role.

    Returns:
        Each offending scenario with ``"ungated"`` when it reaches no enabled
        ``sso`` or ``ldap`` gate, or ``"mismatch"`` when its ``sso`` and ``ldap``
        gates equal none of the ``administrator:`` tests of its module that gate
        on one of the services it gates on.
    """
    items = list(items)
    admins = [
        i.scenario for i in items if i.scenario.title.startswith("administrator:")
    ]
    offenders: list[tuple[Scenario, str]] = []
    for item in items:
        if not is_biber_scenario(item):
            continue
        scenario = item.scenario
        gates = _sign_in_gates(scenario)
        if not _enabled(gates):
            offenders.append((scenario, "ungated"))
            continue
        matching = {
            _sign_in_gates(admin)
            for admin in admins
            if admin.file == scenario.file
            and _enabled(_sign_in_gates(admin)) & _enabled(gates)
        }
        if matching and gates not in matching:
            offenders.append((scenario, "mismatch"))
    return offenders


def assertions_in(code: str) -> Iterator[Assertion]:
    """Yield every ``expect(...)`` of a comment-free JavaScript fragment.

    Args:
        code: a :class:`PersonaTest` ``code``.

    Returns:
        One :class:`Assertion` per ``expect``, ``expect.poll`` or ``expect.soft``
        call followed by a matcher, with the first argument of each side.
    """
    _, skeleton = _lex(code)
    for match in _EXPECT_RE.finditer(skeleton):
        open_idx = match.end() - 1
        close = _close_of(skeleton, open_idx)
        tail = _MATCHER_RE.match(skeleton, close + 1) if close != -1 else None
        if tail is None:
            continue
        subject_start, subject_end = _first_argument(skeleton, open_idx, close)
        matcher_open = tail.end() - 1
        matcher_close = _close_of(skeleton, matcher_open)
        expected = ""
        if matcher_close != -1:
            start, end = _first_argument(skeleton, matcher_open, matcher_close)
            expected = code[start:end].strip()
        yield Assertion(
            code[subject_start:subject_end].strip(),
            bool(tail.group(1)),
            tail.group(2),
            expected,
        )


def is_surface(assertion: Assertion) -> bool:
    """Tell whether an assertion pins what the page renders for its viewer.

    Args:
        assertion: one :func:`assertions_in` result.
    """
    if assertion.negated:
        return False
    if assertion.matcher in _WEB_FIRST:
        return True
    if assertion.matcher == _COUNT:
        return assertion.expected not in ("", "0")
    return assertion.matcher in _VALUE_MATCHERS and bool(
        _PAGE_READ_RE.search(assertion.subject)
    )


def asserts_admin_ui(assertion: Assertion) -> bool:
    """Tell whether a surface assertion expects an admin-only element or path.

    Args:
        assertion: one :func:`assertions_in` result.
    """
    return is_surface(assertion) and bool(
        _ADMIN_RE.search(assertion.subject) or _ADMIN_RE.search(assertion.expected)
    )


def _biber_only_session(item: PersonaTest) -> bool:
    return not (
        _SECOND_SESSION_RE.search(item.code) or _ADMIN_GRANT_RE.search(item.code)
    )


def _ends_on_surface(item: PersonaTest) -> bool:
    return runs_biber_flow(item) or any(is_surface(a) for a in assertions_in(item.code))


def end_surface_offenders(items: Iterable[PersonaTest]) -> list[tuple[Scenario, str]]:
    """Return the biber scenarios that break the end-surface rule.

    Args:
        items: :func:`persona_tests_in` results of one role.

    Returns:
        The role's first ``biber:`` scenario with ``"no-surface"`` when none of
        its ``biber:`` tests runs ``runBiberFlow`` or reaches an assertion that
        pins the rendered page, then each ``biber:`` scenario with
        ``"admin-ui"`` whose lone biber session expects an admin-only element
        or path.
    """
    biber = [i for i in items if i.scenario.title.startswith("biber:")]
    offenders = [
        (item.scenario, "admin-ui")
        for item in biber
        if _biber_only_session(item)
        and any(asserts_admin_ui(a) for a in assertions_in(item.code))
    ]
    if biber and not any(_ends_on_surface(item) for item in biber):
        offenders.insert(0, (biber[0].scenario, "no-surface"))
    return offenders


def application_roles(rbac: object) -> frozenset[str]:
    """Return the application roles an RBAC contract can map biber to.

    Args:
        rbac: the parsed ``meta/rbac.yml`` of a role.

    Returns:
        The declared role names without ``administrator`` and the ``mcp``
        machine role.
    """
    roles = rbac.get("roles") if isinstance(rbac, dict) else None
    if not isinstance(roles, dict):
        return frozenset()
    return frozenset(roles) - _UNMAPPED_ROLES


def _absence(assertion: Assertion) -> bool:
    return (
        assertion.negated
        or assertion.matcher in _ABSENCE_MATCHERS
        or (assertion.matcher == "toHaveCount" and assertion.expected == "0")
        or (
            assertion.matcher in _EQUALITY_MATCHERS
            and assertion.expected in _ABSENT_VALUES
        )
        or bool(_REFUSAL_RE.search(assertion.expected))
        or (
            assertion.matcher == "toContain"
            and bool(_REFUSAL_RE.search(assertion.subject))
        )
    )


def pins_the_role(items: Iterable[PersonaTest], roles: Iterable[str]) -> bool:
    """Tell whether a role's biber tests pin the application role biber maps to.

    Args:
        items: :func:`persona_tests_in` results of one role.
        roles: :func:`application_roles` of the role's RBAC contract.

    Returns:
        True when a ``biber:`` test reaches an assertion that names one of
        ``roles``, or an absence or refusal assertion whose subject, expected
        value or test title names an admin-scoped element, path or role.
    """
    names = "|".join(re.escape(role) for role in sorted(roles))
    role_re = re.compile(rf"(?i)(?<![\w$-])(?:{names})(?![\w$-])") if names else None
    for item in items:
        if not item.scenario.title.startswith("biber:"):
            continue
        admin_title = bool(_ADMIN_SCOPE_RE.search(item.scenario.title))
        for assertion in assertions_in(item.code):
            sides = (assertion.subject, assertion.expected)
            if role_re and any(role_re.search(side) for side in sides):
                return True
            if _absence(assertion) and (
                admin_title or any(_ADMIN_SCOPE_RE.search(side) for side in sides)
            ):
                return True
    return False


def biber_coverage_section(readme: str) -> str | None:
    """Return the body of a README's ``Biber coverage`` section, if it has one.

    Args:
        readme: the role README text.
    """
    match = _BIBER_SECTION_RE.search(readme)
    return match.group(1) if match else None


def role_pin_gap(items: Iterable[PersonaTest], rbac: object, readme: str) -> bool:
    """Tell whether a role leaves a bare biber post-login check unflagged.

    Args:
        items: :func:`persona_tests_in` results of one role.
        rbac: the parsed ``meta/rbac.yml`` of the role.
        readme: the role README text.

    Returns:
        True when the RBAC contract offers biber an application role, the role
        has ``biber:`` tests, none of them pins that role and the README carries
        no non-empty ``Biber coverage`` section.
    """
    items = list(items)
    roles = application_roles(rbac)
    if not roles or not any(i.scenario.title.startswith("biber:") for i in items):
        return False
    if pins_the_role(items, roles):
        return False
    section = biber_coverage_section(readme)
    return not (section and section.strip())


def _report(header: list[str], offenders: list[Scenario]) -> str:
    body = [f"  {s.file}:{s.line_no}: {s.title[:140]}" for s in sorted(offenders)]
    return "\n".join([*header, "", "Offenders:", *body])


def _readme(role: str) -> str | None:
    readme = PROJECT_ROOT / "roles" / role / ROLE_FILE_README
    return read_text(str(readme)) if readme.is_file() else None


def _readme_section(role: str) -> str | None:
    readme = _readme(role)
    return ldap_coverage_section(readme) if readme is not None else None


def _signs_personas_in(role: str) -> bool:
    role_dir = PROJECT_ROOT / "roles" / role
    services = role_dir / ROLE_FILE_META_SERVICES
    env = role_dir / _ENV_TEMPLATE_REL
    if not services.is_file() or not env.is_file():
        return False
    if not declares_ldap(load_yaml_any(str(services), default_if_missing={})):
        return False
    return bool(_PERSONA_CREDENTIAL_RE.search(read_text(str(env))))


class TestPersonaSpecs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.by_role = role_persona_tests()
        cls.scenarios_by_role = {
            role: [item.scenario for item in items]
            for role, items in cls.by_role.items()
            if items
        }
        cls.scenarios = [
            scenario
            for scenarios in cls.scenarios_by_role.values()
            for scenario in scenarios
        ]

    def test_persona_tests_were_found(self) -> None:
        self.assertTrue(self.by_role, "no Playwright test(...) found to scan")

    def test_scenarios_were_found(self) -> None:
        self.assertTrue(self.scenarios, "no Playwright test(...) found to scan")

    def test_sso_and_ldap_gates_use_the_canonical_helpers(self) -> None:
        roots = _scan_targets()
        self.assertTrue(roots, "no Playwright spec files found to scan")
        violations: list[Violation] = []
        for rels in roots.values():
            texts = {rel: read_text(str(PROJECT_ROOT / rel)) for rel in rels}
            bindings = bindings_in(texts.values())
            for rel, text in texts.items():
                violations.extend(
                    Violation(rel, line_no, condition)
                    for line_no, condition in findings_in(text, bindings)
                )
        if violations:
            header = [
                f"Playwright gates on sso/ldap outside the canonical helpers ({len(violations)}):",
                "",
                'Replace each gate with skipUnlessServiceEnabled("sso"|"ldap") or',
                'skipUnlessServiceDisabled("sso"|"ldap") from ./service-gating, so the',
                "reporter shows the canonical <SVC>_SERVICE_ENABLED=<value> reason. Where a",
                "value must exist while the service is on, assert it with expect(...) after",
                "the skip. Suppress on the skip's line or the line above it with",
                f"`// nocheck: {RULE} -- <reason>`.",
                "",
                "Offenders:",
            ]
            body = [
                f"  {v.file}:{v.line_no}: {v.condition[:160]}"
                for v in sorted(violations)
            ]
            self.fail("\n".join(header + body))

    def test_ldap_scenarios_gate_on_ldap(self) -> None:
        offenders = ungated_ldap_scenarios(self.scenarios)
        if offenders:
            self.fail(
                _report(
                    [
                        f"Playwright tests naming LDAP without the ldap gate ({len(offenders)}):",
                        "",
                        'Call skipUnlessServiceEnabled("ldap") from ./service-gating at the top of',
                        "the test, so a deploy with disable=ldap reports it as",
                        "skipped: LDAP_SERVICE_ENABLED=false.",
                    ],
                    offenders,
                )
            )

    def test_ldap_scenarios_carry_a_persona_token(self) -> None:
        offenders = unpersonified_ldap_scenarios(self.scenarios)
        if offenders:
            self.fail(
                _report(
                    [
                        f"ldap-gated Playwright tests naming a persona without its token ({len(offenders)}):",
                        "",
                        "Start the title with administrator:, biber: or guest: so the reporter",
                        "groups the LDAP scenario with its persona.",
                    ],
                    offenders,
                )
            )

    def test_sso_and_ldap_scenarios_keep_separate_bodies(self) -> None:
        offenders = combined_sso_ldap_scenarios(self.scenarios)
        if offenders:
            self.fail(
                _report(
                    [
                        f"Playwright tests gated on both sso and ldap ({len(offenders)}):",
                        "",
                        'Gate the LDAP sign-in on skipUnlessServiceEnabled("ldap") alone and let',
                        'isServiceEnabled("sso") pick the front door at runtime, or split the SSO',
                        "journey into its own sso-gated test, so every variant drives the branch",
                        "it deploys.",
                    ],
                    offenders,
                )
            )

    def test_ldap_capable_roles_ship_an_ldap_scenario(self) -> None:
        offenders: list[str] = []
        for role, scenarios in sorted(self.scenarios_by_role.items()):
            if not _signs_personas_in(role):
                continue
            if _ldap_gated(scenarios) or _readme_section(role) is not None:
                continue
            offenders.append(role)
        if offenders:
            self.fail(
                f"Roles with ldap.enabled and an authenticated spec but no ldap-gated test ({len(offenders)}):\n\n"
                'Add a scenario gated by skipUnlessServiceEnabled("ldap") that drives the role\'s own\n'
                "LDAP-bind login, or state the exemption in a '## LDAP coverage' README section.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_admin_only_ldap_roles_flag_the_biber_follow_up(self) -> None:
        offenders: list[str] = []
        for role, scenarios in sorted(self.scenarios_by_role.items()):
            if not lacks_biber_ldap_scenario(scenarios):
                continue
            section = _readme_section(role)
            if section is None or not _BIBER_RE.search(section):
                offenders.append(role)
        if offenders:
            self.fail(
                f"Roles signing only the administrator in over LDAP ({len(offenders)}):\n\n"
                'Add a biber: scenario gated by skipUnlessServiceEnabled("ldap") or flag the\n'
                "biber follow-up in a '## LDAP coverage' README section.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_biber_only_ldap_roles_flag_the_administrator(self) -> None:
        offenders: list[str] = []
        for role, scenarios in sorted(self.scenarios_by_role.items()):
            if ldap_persona_gap(scenarios) != "administrator":
                continue
            section = _readme_section(role)
            if section is None or not _ADMINISTRATOR_RE.search(section):
                offenders.append(role)
        if offenders:
            self.fail(
                f"Roles signing only biber in over LDAP ({len(offenders)}):\n\n"
                'Add an administrator: scenario gated by skipUnlessServiceEnabled("ldap"), or\n'
                "state in a '## LDAP coverage' README section why the administrator never signs\n"
                "in over LDAP.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_ldap_sign_in_roles_name_their_personas(self) -> None:
        offenders = [
            role
            for role, scenarios in sorted(self.scenarios_by_role.items())
            if ldap_persona_gap(scenarios) == "persona"
            and _signs_personas_in(role)
            and _readme_section(role) is None
        ]
        if offenders:
            self.fail(
                f"Roles whose ldap-gated tests sign no persona in ({len(offenders)}):\n\n"
                'Add administrator: and biber: scenarios gated by skipUnlessServiceEnabled("ldap")\n'
                "that drive the role's LDAP sign-in, or state in a '## LDAP coverage' README\n"
                "section why the role has none.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_biber_scenarios_gate_like_their_administrator(self) -> None:
        offenders = sorted(
            (scenario, reason)
            for items in self.by_role.values()
            for scenario, reason in biber_gate_offenders(items)
        )
        if offenders:
            self.fail(
                f"biber: tests outside runBiberFlow with the wrong sign-in gates ({len(offenders)}):\n\n"
                'Gate the test on skipUnlessServiceEnabled("sso") or ("ldap"), so a deploy with\n'
                "disable=sso,ldap reports it as skipped, and on the same sso and ldap gates as\n"
                "the administrator: tests of its module that gate on one of those services.\n\n"
                "Offenders:\n"
                + "\n".join(
                    f"  {s.file}:{s.line_no}: [{reason}] {s.title[:120]}"
                    for s, reason in offenders
                )
            )

    def test_biber_scenarios_end_on_a_non_admin_surface(self) -> None:
        offenders = sorted(
            (scenario, reason)
            for items in self.by_role.values()
            for scenario, reason in end_surface_offenders(items)
        )
        if offenders:
            self.fail(
                f"biber: scenarios without a non-admin end surface ({len(offenders)}):\n\n"
                "[no-surface]: let one biber: test of the role run runBiberFlow or end on a\n"
                "deterministic surface the biber session renders: a URL (toHaveURL,\n"
                "page.url()), a heading or title (toHaveTitle, toHaveText) or a stable\n"
                "selector (toBeVisible, toBeAttached, toHaveCount(n > 0)).\n"
                "[admin-ui]: never expect an admin-only element or path from a lone biber\n"
                "session.\n\nOffenders:\n"
                + "\n".join(
                    f"  {s.file}:{s.line_no}: [{reason}] {s.title[:120]}"
                    for s, reason in offenders
                )
            )

    def test_bare_biber_checks_are_flagged_in_the_readme(self) -> None:
        offenders: list[str] = []
        for role, items in sorted(self.by_role.items()):
            rbac = load_yaml_any(
                str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_RBAC),
                default_if_missing={},
            )
            if role_pin_gap(items, rbac, _readme(role) or ""):
                offenders.append(role)
        if offenders:
            self.fail(
                f"roles whose biber: tests prove only a bare post-login page ({len(offenders)}):\n\n"
                "The role's meta/rbac.yml offers biber an application role, but no biber:\n"
                "assertion names that role or expects an admin-scoped element, path or\n"
                "response to be absent or refused. Pin the role in a biber: test, or flag the\n"
                "bare check in a README '## Biber coverage' section so a follow-up can tighten\n"
                "it.\n\nOffenders:\n"
                + "\n".join(f"  roles/{role}" for role in offenders)
            )


if __name__ == "__main__":
    unittest.main()
