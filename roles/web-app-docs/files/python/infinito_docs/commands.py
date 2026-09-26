"""The commands that build one version of the documentation and the progress they report."""

from __future__ import annotations

import re
import sys

_STEP = re.compile(
    r"^(reading sources|writing output|postprocess html)\.\.\. \[\s*(\d+)%\]"
)
_SPAN = {
    "reading sources": (10, 40),
    "writing output": (40, 60),
    "postprocess html": (60, 99),
}


def _module(name, *args):
    return [sys.executable, "-P", "-m", name, *(str(arg) for arg in args)]


def _generator(name, *args):
    return _module(f"infinito_docs.generators.{name}", *args)


def generate_commands(src):
    """Return the commands that prepare ``src`` for ``sphinx-build``.

    Args:
        src: checkout of the version to document.

    Returns:
        argv lists, in the order they must run.
    """
    generated = src / "generated"
    return [
        [
            sys.executable,
            "-m",
            "sphinx.ext.apidoc",
            "-f",
            "-o",
            str(generated / "modules"),
            str(src),
            str(src / "tests"),
            str(src / "roles"),
            str(src / "library"),
        ],
        _generator(
            "yaml_index",
            "--source-dir",
            src,
            "--output-file",
            generated / "yaml_index.rst",
        ),
        _generator(
            "ansible_roles",
            "--roles-dir",
            src / "roles",
            "--output-dir",
            generated / "roles",
        ),
        _generator(
            "index",
            "--roles-dir",
            generated / "roles",
            "--output-file",
            src / "roles" / "ansible_role_glosar.rst",
            "--caption",
            "Ansible Role Glossary",
        ),
        _generator(
            "roles_overview",
            "--roles-dir",
            src / "roles",
            "--output-file",
            generated / "roles_overview.json",
        ),
        _generator("readmes", "--generated-dir", generated),
        _module(
            "cli.build.docs.readme",
            "--override",
            "--roles-dir",
            src / "roles",
        ),
        _module(
            "cli.build.docs.readme.overview",
            "--readme",
            src / "README.md",
            "--roles-dir",
            src / "roles",
        ),
    ]


def progress_of(line, current):
    """Return the overall build progress after one line of Sphinx output.

    Args:
        line: a line of ``sphinx-build`` output.
        current: progress before this line, in percent.

    Returns:
        The new progress in percent; it never moves backwards.
    """
    match = _STEP.match(line)
    if not match:
        return current
    start, end = _SPAN[match.group(1)]
    return max(current, start + (end - start) * int(match.group(2)) // 100)
