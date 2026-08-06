"""Lint: no ``ARG`` in any Dockerfile carries a default value.

A defaulted ``ARG`` answers a question the caller failed to answer. The build
then succeeds against a base image, version or path nobody chose, and the
mistake surfaces as wrong behaviour at runtime instead of a failed build. Every
build argument MUST be supplied by the caller, so a missing one fails loudly:

    ARG BASE_IMAGE          # required, the compose build passes it
    FROM ${BASE_IMAGE}

Docker itself does not enforce this. An undeclared ``ARG`` used in ``FROM``
expands to the empty string and yields ``invalid reference format``, which is
the loud failure this lint preserves by refusing the default that would have
hidden it.

Covers every Dockerfile the repository tracks, including ``.j2`` templates and
paths outside ``roles/``. A Jinja template MAY interpolate the value, which is
still the caller supplying it, not a default.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: dockerfile-arg-default`` on, or directly above, the ARG line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

_RULE = "dockerfile-arg-default"

_ARG_WITH_DEFAULT = re.compile(r"^\s*ARG\s+(\w+)\s*=", re.IGNORECASE)


def _is_dockerfile(path: str) -> bool:
    name = Path(path).name
    return name == "Dockerfile" or name.startswith("Dockerfile.")


def collect_dockerfiles() -> list[Path]:
    """Return every tracked Dockerfile, template variants included."""
    return sorted(
        Path(candidate)
        for candidate in iter_non_ignored_files()
        if _is_dockerfile(candidate)
    )


def defaulted_args(dockerfile: Path) -> list[tuple[int, str]]:
    """Return ``(line_number, arg_name)`` for every defaulted ARG.

    Args:
        dockerfile: the Dockerfile to scan.
    """
    lines = read_text(str(dockerfile)).splitlines()
    findings = []
    for index, line in enumerate(lines, start=1):
        match = _ARG_WITH_DEFAULT.match(line)
        if match and not is_suppressed_at(lines, index, _RULE):
            findings.append((index, match.group(1)))
    return findings


class TestDockerfileArgWithoutDefault(unittest.TestCase):
    def test_dockerfiles_exist(self) -> None:
        self.assertTrue(
            collect_dockerfiles(),
            "no Dockerfile found; the scan would pass vacuously",
        )

    def test_no_arg_carries_a_default(self) -> None:
        failures = []
        for dockerfile in collect_dockerfiles():
            relative = dockerfile.relative_to(PROJECT_ROOT).as_posix()
            failures.extend(
                f"{relative}:{line}: ARG {name} carries a default"
                for line, name in defaulted_args(dockerfile)
            )

        self.assertFalse(
            failures,
            f"{len(failures)} ARG default(s). A build argument MUST be supplied "
            "by the caller so a missing one fails the build instead of "
            "silently selecting a base image, version or path nobody chose. "
            "Drop the default and pass the value from the compose build "
            "arguments:\n\n" + "\n".join(f"  {f}" for f in failures),
        )


if __name__ == "__main__":
    unittest.main()
