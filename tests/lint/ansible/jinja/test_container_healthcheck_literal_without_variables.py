"""A literal ``healthcheck:`` block that needs no template variable belongs in
``meta/services.yml``.

``utils/docker/healthcheck`` is the single point of truth for probe timings. It
carries ``start_interval``, the cadence Docker uses while ``start_period`` is
still running; without it a probe only fires every ``interval``, so a service
ready after three seconds is reported healthy at the next tick and a stack
converges no faster than its slowest quantisation. A block written out in the
template bypasses that default and never gains it, which is how forty six of
them ended up without the key.

Moving the block is mechanical and provably lossless: the lookup writes
``overrides.get(key, flavor_default)`` for each of ``interval``, ``timeout``,
``retries``, ``start_period`` and ``start_interval``, so a declaration that
repeats the literal values renders the same block plus the missing cadence.

A block that interpolates a template variable is exempt. Its value is resolved
in the template's own scope, which ``meta/services.yml`` does not share, so
moving it is a rewrite rather than a transcription.

Per-block opt-out
=================
``# nocheck: container-healthcheck-literal`` on the ``healthcheck:`` line or the
line directly above it, with a short reason. Reserved for a block that is
variable free yet still cannot move: a partial rendered for another role's
``application_id``, or timings the flavor defaults would make worse.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

RULE = "container-healthcheck-literal"
SCAN_PREFIX = "roles/"
SCAN_EXTENSIONS = (".j2",)

_HEALTHCHECK = re.compile(r"^(\s*)healthcheck:\s*(?:#.*)?$")
_VARIABLE = ("{{", "{%")


def _block_body(lines: list[str], index: int, indent: int) -> list[str]:
    """Return the lines nested under the ``healthcheck:`` at *index*.

    Args:
        lines: the whole template.
        index: 0-based line number of the ``healthcheck:`` key.
        indent: that key's indentation width.
    """
    body: list[str] = []
    for line in lines[index + 1 :]:
        if not line.strip():
            break
        if len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return body


def literal_blocks_without_variables() -> list[tuple[str, int]]:
    """Every variable free literal healthcheck block, as ``(path, line_no)``."""
    findings: list[tuple[str, int]] = []
    for path_str, content in iter_project_files_with_content(
        extensions=SCAN_EXTENSIONS,
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith(SCAN_PREFIX):
            continue
        lines = content.splitlines()
        for index, line in enumerate(lines):
            match = _HEALTHCHECK.match(line)
            if not match:
                continue
            body = _block_body(lines, index, len(match.group(1)))
            if not body:
                continue
            if any(token in "\n".join(body) for token in _VARIABLE):
                continue
            line_no = index + 1
            if is_suppressed_at(lines, line_no, RULE):
                continue
            findings.append((rel, line_no))
    return findings


class TestContainerHealthcheckLiteralWithoutVariables(unittest.TestCase):
    def test_variable_free_healthchecks_live_in_meta(self) -> None:
        findings = literal_blocks_without_variables()
        if not findings:
            return
        formatted = "\n".join(f"- {path}:{line}" for path, line in sorted(findings))
        self.fail(
            "Found literal 'healthcheck:' blocks that interpolate nothing and so "
            "belong in meta/services.yml, where the container_healthcheck SPOT "
            "adds the start_interval cadence a hand written block never gains.\n\n"
            "Fix: copy the block's keys to services.<key>.healthcheck in "
            "meta/services.yml and render it with\n\n"
            "    {{ lookup('container_healthcheck', service_name) | indent(4) }}\n\n"
            "Cannot move (a partial rendered for another role, or timings the "
            "flavor defaults would worsen)? Add on the healthcheck line or the "
            f"line above it:\n\n    # nocheck: {RULE}  <short reason>\n\n"
            f"Offenders:\n{formatted}"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
