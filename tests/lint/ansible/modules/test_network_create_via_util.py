"""Forbid ad-hoc docker-network creation outside the central utils.

Every role that needs a docker network MUST go through one of two
canonical helpers, both under
``roles/sys-svc-compose/tasks/utils/network/``:

  1. ``create.yml`` -- network-only, no compose-up.
     Use when the role still needs to do work between the network
     creation and the compose-up (e.g. copy entrypoint/healthcheck
     files into the instance dir, render extra configs, pre-attach
     other resources). Also the right choice when pre-creating
     multiple foreign networks in a loop (prometheus's
     ``native_metrics_apps`` pre-create), where re-flushing
     sys-svc-compose per iteration would be wrong.

  2. ``routine.yml`` -- wrapper that loads the docker-python deps,
     calls ``create.yml`` for the role's own network, and then
     immediately re-includes ``sys-svc-compose`` with
     ``compose_handlers_flush: true`` to fire compose-up.
     Use when the role is a self-contained single-container service
     whose only pre-condition for compose-up is its own network
     (mariadb, postgres, ollama).

Both helpers derive the docker-side network name from
``role_id | get_entity_name`` and the subnet from
``meta/server.yml.networks.local.subnet``, so the mapping stays in one
place. Ad-hoc ``community.docker.docker_network`` calls or shell-out
to ``docker network create`` / ``container network create`` reintroduce
the drift the utils were extracted to prevent.

Allowed (by path): only ``create.yml`` itself; the wrapper
``routine.yml`` already delegates to it via ``include_tasks``.

Detected antipatterns:
  - ``community.docker.docker_network:`` (the underlying Ansible module)
  - ``docker_network:`` (short / collection-less alias)
  - ``docker network create`` / ``container network create`` inside any
    shell, command, or run body
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

SCAN_DIRS = ("roles",)
_SCAN_PREFIXES = tuple(f"{d}/" for d in SCAN_DIRS)
SCAN_SUFFIXES = (".yml", ".yaml")

_ALLOWED_PATH = "roles/sys-svc-compose/tasks/utils/network/create.yml"

_MODULE_RE = re.compile(
    r"^\s*(?:-\s+)?(?:community\.docker\.)?docker_network\s*:",
)
_CLI_RE = re.compile(r"\b(?:docker|container)\s+network\s+create\b")


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    snippet: str
    kind: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: [{self.kind}] {self.snippet}"


def _iter_target_files(repo_root: Path) -> Iterable[Path]:
    for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
        rel = Path(abs_path).relative_to(repo_root).as_posix()
        if not any(rel.startswith(p) for p in _SCAN_PREFIXES):
            continue
        if rel == _ALLOWED_PATH:
            continue
        yield Path(abs_path)


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        if _MODULE_RE.match(line):
            findings.append(
                Finding(file=path, line=idx, snippet=line.strip(), kind="module"),
            )
        elif _CLI_RE.search(line):
            findings.append(
                Finding(file=path, line=idx, snippet=line.strip(), kind="cli"),
            )
    return findings


class TestNetworkCreateViaUtil(unittest.TestCase):
    def test_docker_networks_only_created_via_central_util(self) -> None:
        """Docker networks MUST be created via the canonical utils
        under ``roles/sys-svc-compose/tasks/utils/``.

        Two entry points exist; pick the one that matches the role's
        compose-up timing:

        1. ``create.yml`` -- network-only, no compose-up.
           Use when the role does extra setup between the network
           creation and the compose-up (asset copies, configs, ...),
           OR when pre-creating multiple foreign networks in a loop::

               - include_tasks: "{{ lookup('path_absolute', 'roles/sys-svc-compose/tasks/utils/network/create.yml') }}"
                 vars:
                   network_role_id: "{{ application_id }}"

        2. ``routine.yml`` -- wrapper that includes
           ``create.yml`` AND immediately re-flushes
           ``sys-svc-compose`` so the role's compose-up runs right
           after. Use for self-contained single-container services
           (mariadb / postgres / ollama)::

               - include_tasks: "{{ lookup('path_absolute', 'roles/sys-svc-compose/tasks/utils/network/routine.yml') }}"
                 vars:
                   compose_handlers_flush: true

        Both derive name (``role_id | get_entity_name``) and subnet
        (``meta/server.yml.networks.local.subnet``) automatically.
        Calling ``community.docker.docker_network`` directly or
        shelling out to ``docker network create`` re-introduces the
        name/subnet drift the utils were extracted to prevent.
        """
        findings: list[Finding] = []
        for path in _iter_target_files(PROJECT_ROOT):
            findings.extend(_scan_file(path))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                f"Found {len(findings)} ad-hoc docker-network "
                "creation(s) outside the central utils:\n"
                f"{formatted}\n\n"
                "Replace with `include_tasks` of one of:\n"
                "  - `roles/sys-svc-compose/tasks/utils/network/create.yml` "
                "(network only -- when the role still needs to do work "
                "before compose-up, or when pre-creating foreign "
                "networks in a loop), or\n"
                "  - `roles/sys-svc-compose/tasks/utils/network/routine.yml` "
                "(wrapper -- when the role wants the full network + "
                "immediate compose-up chain, e.g. self-contained "
                "single-container services).\n"
                "Pass `network_role_id` (network-only util) or rely on "
                "`application_id` in scope (wrapper). Both derive name "
                "and subnet from the role's `meta/server.yml`.",
            )


if __name__ == "__main__":
    unittest.main()
