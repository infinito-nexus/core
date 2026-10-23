"""Lint guard: an env value defaulted to ``""`` MUST be handled or required.

A spec that writes ``const baseUrl = normalizeBaseUrl(process.env.X_BASE_URL ||
"")`` and then navigates to ```${baseUrl}/`` `` goes to ``/`` when the deploy
does not write the key. Nothing fails; the spec tests the wrong target. The
matcher shape is worse still, because ``""`` is a prefix, a suffix and a
substring of every string, so ``url.includes(host)`` passes unconditionally.

The repository already refuses the list-shaped half of this: the throwing
``decodeDotenvJsonList`` exists because reading a mis-decoded list as ``[]``
"would pass every assertion that iterates it".

An empty default is accepted only where the file says what empty means. Three
forms count as handled:

* the binding is made with ``requireDotenvValue``, which throws at module load;
* the binding expression carries its own second fallback, such as
  ``JSON.parse(decodeDotenvQuotedValue(process.env.X || "") || "{}")``;
* the binding expression compares the value itself, as in
  ``(process.env.X || "").toLowerCase() === "true"``, where empty is simply
  not equal;
* the name's emptiness is tested somewhere in the file, through
  ``expect(name, ...)``, ``if (!name)``, ``!name``, ``name === ...`` or
  ``name ? ... : ...``.

Everything else consumes the value unconditionally and is reported.

Suppress on the binding line with
``// nocheck: unguarded-env-default -- <reason>``.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_BINDING_RE = re.compile(
    r"^[^\S\n]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(.*?);[^\S\n]*$",
    re.MULTILINE,
)
_EMPTY_DEFAULT_RE = re.compile(r"\|\|\s*\"\"")
_SECOND_FALLBACK_RE = re.compile(
    r"\|\|\s*\"\"\s*\)?\s*\|\||\|\|\s*(?:\"[^\"]+\"|\{\}|\[\]|0|false|null)"
)
_SELF_COMPARING_RE = re.compile(r"===|!==")
_NOCHECK_RE = re.compile(r"//\s*nocheck:\s*unguarded-env-default\b")


@dataclass(frozen=True, order=True)
class Violation:
    file: str
    line_no: int
    name: str


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(PROJECT_ROOT), "ls-files"],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _emptiness_is_tested(text: str, name: str) -> bool:
    escaped = re.escape(name)
    probes = (
        rf"expect\(\s*{escaped}\b",
        rf"if\s*\(\s*!?\s*{escaped}\b",
        rf"!\s*{escaped}\b",
        rf"{escaped}\s*(?:===|!==|\?)",
    )
    return any(re.search(probe, text) for probe in probes)


def _scan_file(path: Path) -> list[Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[Violation] = []
    for match in _BINDING_RE.finditer(text):
        name, expression = match.group(1), match.group(2)
        if "process.env." not in expression:
            continue
        if not _EMPTY_DEFAULT_RE.search(expression):
            continue
        if _NOCHECK_RE.search(match.group(0)):
            continue
        if _SECOND_FALLBACK_RE.search(expression):
            continue
        if _SELF_COMPARING_RE.search(expression):
            continue
        if _emptiness_is_tested(text, name):
            continue
        line_no = text.count("\n", 0, match.start()) + 1
        violations.append(Violation(rel, line_no, name))
    return violations


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in _git_ls_files()
        if rel.endswith(".js")
        and ("/files/playwright/" in rel or "/files/personas/" in rel)
    ]


class TestUnguardedEnvDefault(unittest.TestCase):
    def test_empty_env_defaults_are_handled_or_required(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no Playwright spec files found to scan")
        violations: list[Violation] = []
        for path in targets:
            violations.extend(_scan_file(path))
        if violations:
            header = [
                f'Env values defaulted to "" that nothing handles ({len(violations)}):',
                "",
                "The spec consumes the value unconditionally, so a key the deploy",
                "never wrote turns into an empty string that navigates to `/`, or",
                "into a matcher argument every string satisfies.",
                "",
                'Bind with `requireDotenvValue(process.env.<KEY>, "<KEY>")`, which',
                "throws at module load, or handle emptiness in the file: give the",
                "binding a second fallback, or test the name before using it.",
                "Suppress on the binding line with",
                "`// nocheck: unguarded-env-default -- <reason>`.",
                "",
                "Offenders:",
            ]
            body = [f"  {v.file}:{v.line_no}: {v.name}" for v in sorted(violations)]
            self.fail("\n".join(header + body))


if __name__ == "__main__":
    unittest.main()
