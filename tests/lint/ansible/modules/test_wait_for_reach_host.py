"""Lint guard: a ``wait_for`` readiness probe MUST dial ``DOCKER_REACH_HOST``.

``wait_for`` opens a plain TCP socket from the Ansible controller. The public
domain of a role is the wrong target for that: it resolves only where the
deployment's own name resolution already works, and it routes only where the
ingress is reachable from the controller. On an onion deployment it is neither -
a ``.onion`` authority needs Tor's SOCKS resolver, so the probe cannot connect
and burns its whole timeout before failing a deploy whose service was up the
entire time. ``roles/web-app-nextcloud/tasks/addons/integration_gitlab_provision.yml``
did exactly that in run 31823845576, spending ``elapsed: 600`` on
``lab.git.<onion>:80``.

``DOCKER_REACH_HOST`` (``group_vars/all/00_general.yml``) is the answer the
repository already settled on: ``127.0.0.1``, swapped for the Docker bridge
gateway when the controller itself runs in a container. Paired with the
service's ``ports.local.*`` it reaches the container under test without
depending on DNS, the front proxy, or the onion. Every other readiness probe in
``roles/`` uses it.

A probe that genuinely must traverse the public name - one that is verifying the
ingress itself rather than the backend's readiness - opts out with
``# nocheck: wait-for-reach-host`` on the ``host:`` line or above the
``wait_for:`` key, naming what it is proving.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "wait-for-reach-host"
_WAIT_FOR = re.compile(r"^(\s*)wait_for\s*:\s*(?:#.*)?$")
_HOST = re.compile(r"^\s*host\s*:\s*(?P<value>.+?)\s*(?:#.*)?$")
_EXPECTED = "DOCKER_REACH_HOST"


def _host_line_of_block(lines: list[str], start: int) -> tuple[int, str] | None:
    """Return the (1-based line number, value) of the block's ``host:`` key.

    Args:
        lines: the file's lines.
        start: 0-based index of the ``wait_for:`` line.

    The block ends at the first line indented no deeper than the ``wait_for:``
    key itself, which is where the next task key or the next list item starts.
    """
    indent = len(lines[start]) - len(lines[start].lstrip())
    for offset in range(start + 1, len(lines)):
        line = lines[offset]
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= indent:
            return None
        match = _HOST.match(line)
        if match:
            return offset + 1, match.group("value")
    return None


class TestWaitForReachHost(unittest.TestCase):
    def test_every_wait_for_probe_dials_the_reach_host(self) -> None:
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            lines = content.splitlines()
            for index, line in enumerate(lines):
                if not _WAIT_FOR.match(line):
                    continue
                found = _host_line_of_block(lines, index)
                if found is None:
                    continue
                host_line_no, value = found
                if _EXPECTED in value:
                    continue
                if is_suppressed_at(lines, host_line_no, _RULE) or is_suppressed_at(
                    lines, index + 1, _RULE
                ):
                    continue
                findings.append((rel, host_line_no, value))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: host: {value}"
                for path, line_no, value in sorted(findings)
            )
            self.fail(
                "wait_for probes must dial DOCKER_REACH_HOST, not a public name.\n\n"
                "A plain TCP socket from the controller cannot resolve or route an "
                "onion authority, and only reaches a clearnet domain where the "
                "ingress happens to be reachable; the probe then burns its whole "
                "timeout while the service is up. Use "
                '`host: "{{ DOCKER_REACH_HOST }}"` with the service\'s '
                "`ports.local.*`, or mark the line "
                f"`# nocheck: {_RULE}` naming what the probe proves.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
