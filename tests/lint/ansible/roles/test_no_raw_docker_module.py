"""Enforce that role tasks manage containers through the ``container``
CLI wrapper instead of the raw ``community.docker.docker_*`` modules.

Rationale
=========
``roles/sys-svc-container/files/container.py`` is installed as the
``container`` binary and is the single SPOT for talking to the container
runtime: it injects the project root CA (``container run``), and every
other subcommand is a passthrough to ``docker <subcommand>`` so the same
task body works under compose, swarm, and docker-in-docker.

The ``community.docker.docker_container`` module (and its
``docker_network`` / ``docker_image`` / ``docker_*_info`` siblings) talks
to the docker socket directly. It bypasses the CA-aware wrapper, is blind
to swarm service naming, and splits container lifecycle across two
mechanisms. Route the operation through ``container`` via
``ansible.builtin.command`` / ``ansible.builtin.shell`` instead, e.g.::

    - name: "▶️ Start recovery container"
      ansible.builtin.command:
        argv: [container, run, --name, "{{ X_NAME }}", ...]

Per-line opt-out
================
Add ``# nocheck: docker-module-uses-container-cli`` on the same line as
the ``community.docker.docker_*:`` key OR on the immediately preceding
non-empty line. Legitimate uses are rare (an operation the wrapper
genuinely cannot express) and MUST carry the reason inline.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "docker-module-uses-container-cli"

_MODULE_RE = re.compile(r"^\s*community\.docker\.docker_[a-z_]+\s*:")


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and (
        "/tasks/" in rel_path or "/handlers/" in rel_path
    )


def _is_comment_line(line: str) -> bool:
    return line.lstrip().startswith("#")


class TestNoRawDockerModule(unittest.TestCase):
    def test_roles_use_container_cli_not_docker_modules(self) -> None:
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if _is_comment_line(line):
                    continue
                if not _MODULE_RE.match(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    set(findings), key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found `community.docker.docker_*` module calls in role "
                "tasks/handlers. These bypass the CA-aware `container` "
                "wrapper (roles/sys-svc-container/files/container.py) and "
                "are blind to swarm service naming.\n\n"
                "Fix: drive the operation through the `container` CLI, e.g.\n\n"
                "    - ansible.builtin.command:\n"
                '        argv: [container, run, --name, "{{ X_NAME }}", ...]\n\n'
                "Or, where the wrapper genuinely cannot express the "
                "operation, add `# nocheck: docker-module-uses-container-cli` "
                "on the same line or the line immediately above, with the "
                "reason.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
