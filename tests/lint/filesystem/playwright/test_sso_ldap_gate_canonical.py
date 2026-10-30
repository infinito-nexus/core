"""Lint guard: Playwright gates on ``sso`` and ``ldap`` use the canonical helpers.

``skipUnlessServiceEnabled("<svc>")`` and ``skipUnlessServiceDisabled("<svc>")`` from
``./service-gating`` skip with the canonical ``<SVC>_SERVICE_ENABLED=<value>`` reason.
A ``test.skip(...)`` or ``test.fixme(...)`` whose condition reads an ``sso``, ``ldap``
or ``oidc`` value gates the same service with a free-text reason instead. The condition
is read directly, through a ``const``/``let``/``var`` or object-property binding
anywhere in the role's Playwright directory, or from the ``if`` that wraps an
unconditional skip. ``isSplitRealmOidc()`` stays out of the match.

Suppress on the skip's line or the line above it with
``// nocheck: playwright-sso-ldap-gate -- <reason>``; a marker without a reason of at
least ten characters grants nothing.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text, repository_files

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

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


@dataclass(frozen=True, order=True)
class Violation:
    file: str
    line_no: int
    condition: str


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


def _lex(text: str) -> tuple[str, str]:
    """Split JavaScript source into two offset-preserving views.

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


class TestSsoLdapGateCanonical(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
