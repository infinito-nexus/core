"""Lint: a shell script shipped as a Jinja template still gets checked.

``make lint-shellcheck`` walks files on disk, so a ``*.sh.j2`` is invisible to
it: the thing that actually runs on the host is the render, and nothing looks at
the render until it fails on a node. That is an unpleasant place to discover a
quoting mistake in a script which runs as root and rewrites the host packet
filter.

Every ``roles/*/templates/*.sh.j2`` is rendered here and handed to ``bash -n``,
plus ``shellcheck`` where it is installed. A value the lint does not know
renders as a placeholder token and an unknown collection renders as empty, so
the check judges the shape of the script rather than what a particular
deployment puts in it. Where a template's structure only becomes real with
concrete values, those live in ``_SAMPLE``.

``SC2034`` is excluded: emptying a conditional branch orphans the variables that
branch used, so a partial render cannot tell a genuinely unused variable from
one whose only reader was not rendered.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import unittest
from pathlib import Path

import jinja2

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_PARTIAL_RENDER_NOISE = "SC2034"


class _PassthroughFilters(dict):
    """Any filter this environment does not know leaves the value untouched.

    The repo's own filter plugins live in ansible, not in bare jinja2, and the
    check is about the shape of the resulting shell rather than about what a
    filter computes.
    """

    def __missing__(self, name: str):
        def _identity(value: object, *_args: object, **_kwargs: object) -> object:
            return value

        return _identity

    def __contains__(self, name: object) -> bool:
        """Claim every filter, because jinja resolves them at compile time."""
        return True

    def get(self, name: object, default: object = None) -> object:
        """Jinja looks filters up with ``get``, which skips ``__missing__``."""
        return self[name] if name in dict.keys(self) else self.__missing__(str(name))


class _Placeholder(jinja2.Undefined):
    """An unknown value that keeps the rendered script syntactically whole."""

    def __str__(self) -> str:
        return "placeholder"

    def __iter__(self):
        return iter(())

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name: str) -> _Placeholder:
        return self

    def __getitem__(self, key: object) -> _Placeholder:
        return self


_SAMPLE: dict[str, object] = {}


def _shell_templates() -> list[Path]:
    found = []
    for path_str in iter_project_files(extensions=(".j2",)):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith("roles/") and rel.endswith(".sh.j2"):
            found.append(Path(path_str))
    return sorted(found)


class TestShellTemplatesAreValid(unittest.TestCase):
    def test_every_shell_template_renders_to_valid_bash(self) -> None:
        templates = _shell_templates()
        self.assertTrue(templates, "no roles/*/templates/*.sh.j2 found to check")
        shellcheck = shutil.which("shellcheck")
        for path in templates:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            with self.subTest(template=rel):
                environment = jinja2.Environment(
                    undefined=_Placeholder,
                    keep_trailing_newline=True,
                    autoescape=False,  # noqa: S701  shell, not markup
                )
                environment.filters = _PassthroughFilters(environment.filters)
                environment.filters["quote"] = shlex.quote
                environment.globals["lookup"] = lambda *_args, **_kwargs: "placeholder"
                rendered = environment.from_string(read_text(str(path))).render(
                    **_SAMPLE
                )
                syntax = subprocess.run(
                    ["bash", "-n"],
                    input=rendered,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    syntax.returncode,
                    0,
                    f"{rel} does not render to valid bash:\n{syntax.stderr}",
                )
                if shellcheck is None:
                    continue
                report = subprocess.run(
                    [
                        shellcheck,
                        "--shell=bash",
                        f"--exclude={_PARTIAL_RENDER_NOISE}",
                        "-",
                    ],
                    input=rendered,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    report.returncode,
                    0,
                    f"{rel} fails shellcheck once rendered:\n{report.stdout}",
                )


if __name__ == "__main__":
    unittest.main()
