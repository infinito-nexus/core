"""Ban a forwarded variable that the HOST shell expands back into the argv.

Rationale
=========
``container exec -e NAME … prog --flag "$NAME"`` looks like the safe form and
is not. ``ansible.builtin.shell`` hands the whole string to ``/bin/sh -c`` on
the executing host, so that shell expands ``"$NAME"`` itself and writes the
value straight into the argv of ``container exec`` — the very place the
``-e`` was meant to keep it out of. Demonstrated:

    X=secret; set -- container exec -i -e X cid prog --password "$X"
    argv: container exec -i -e X cid prog --password secret

The variable must be expanded by the shell *inside* the container, which
means the command for it has to be quoted away from the host shell:

    container exec -i -e NAME cid sh -lc 'prog --flag "$NAME"'

Single quotes are what make the difference; inside them the host shell leaves
``$NAME`` alone and the inner shell resolves it. ``--entrypoint /bin/sh … -c
'…'`` is the same shape with the interpreter chosen by flag, and passes.

The half-fixed form survives every other check: it carries the ``-e NAME``
and the ``environment:``, it renders, it parses, and the two sibling rules
see nothing wrong with it.

Per-line opt-out
================
``# nocheck: container-env-host-expanded -- <reason>`` on the ``container``
line or the one above it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "container-env-host-expanded"
_EXTENSIONS = (".yml", ".yaml")
_INVOCATION = re.compile(r"\bcontainer\s+(?:exec|run)\b")
_FORWARDED = re.compile(r"-e\s+([A-Z_][A-Z0-9_]*)(?![=\w])")
_SHELL_KEYS = ("shell", "ansible.builtin.shell", "command", "ansible.builtin.command")


def _unquoted_expansions(text: str) -> set[str]:
    """Return the variables expanded outside any single-quoted span.

    Args:
        text: the command as the host shell receives it.

    Returns:
        Every ``NAME`` of a ``$NAME`` or ``${NAME}`` the host shell would
        expand: every occurrence that is neither inside single quotes nor
        preceded by a backslash. A backslash matters here because escaping
        the dollar is the other way to defer expansion to the inner shell,
        and ``roles/web-app-wordpress/tasks/01_patch_config.yml`` relies on
        exactly that.
    """
    names: set[str] = set()
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and not quoted:
            index += 2
            continue
        if char == "'":
            quoted = not quoted
        elif char == "$" and not quoted:
            rest = text[index + 1 :]
            match = re.match(r"\{?([A-Z_][A-Z0-9_]*)\}?", rest)
            if match:
                names.add(match.group(1))
        index += 1
    return names


def _shell_scalars(node):
    """Yield every command text a task hands to a shell.

    Covers the plain scalar, the ``cmd:`` mapping, and an ``argv:`` list
    **whose first element is a host shell**. That last condition is the
    whole point of reading argv at all: ``argv: [bash, -lc, <script>]`` runs
    a host shell just as surely as ``shell:`` does and expands ``$NAME``
    there, while ``argv: [container, exec, …, sh, -c, <script>]`` is exec'd
    directly, so the very same ``$NAME`` travels as a literal and only the
    container's shell resolves it. Reading every argv list alike reports the
    correct form as a defect.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SHELL_KEYS:
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    if isinstance(value.get("cmd"), str):
                        yield value["cmd"]
                    argv = value.get("argv")
                    if isinstance(argv, list) and argv:
                        head = str(argv[0]).rsplit("/", 1)[-1]
                        if head in ("sh", "bash", "ash", "dash", "zsh"):
                            yield "\n".join(
                                part for part in argv if isinstance(part, str)
                            )
            yield from _shell_scalars(value)
    elif isinstance(node, list):
        for item in node:
            yield from _shell_scalars(item)


class TestContainerEnvExpandsInContainer(unittest.TestCase):
    def test_a_forwarded_variable_is_not_expanded_by_the_host(self) -> None:
        findings: list[tuple[str, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_EXTENSIONS
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/") or "/tasks/" not in rel:
                continue
            try:
                doc = load_yaml_any(path_str)
            except Exception:  # pragma: no cover - a malformed file is another rule's
                continue
            lines = content.splitlines()
            for command in _shell_scalars(doc):
                if not _INVOCATION.search(command):
                    continue
                leaked = set(_FORWARDED.findall(command)) & _unquoted_expansions(
                    command
                )
                if not leaked:
                    continue
                line_no = next(
                    (
                        number
                        for number, line in enumerate(lines, 1)
                        if _INVOCATION.search(line)
                    ),
                    1,
                )
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, ", ".join(sorted(leaked))))

        if findings:
            formatted = "\n".join(
                f"- {p}: {names}" for p, names in sorted(set(findings))
            )
            self.fail(
                "Found a variable forwarded with `-e NAME` and then expanded by "
                "the HOST shell, which writes its value back into the argv of "
                "`container exec`. The `-e` buys nothing in that shape.\n\n"
                "Fix: quote the in-container command away from the host shell, "
                "`sh -lc 'prog --flag \"$NAME\"'`, so the container's shell "
                "resolves it.\n\n"
                f"Offending commands:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
