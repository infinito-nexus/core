"""Flag `chdir: "{{ lookup('container', application_id, 'directories.instance') }}"`
in shell or command tasks. That chdir points at the compose project root
(`/opt/compose/<app>/`) which only makes sense for docker-compose-CLI
verbs. Under `docker stack deploy` there is no compose project to chdir
into, so any task carrying that chdir is implicitly compose-only.

Per-line opt-out: ``# nocheck: compose-chdir-in-task`` on the offending
line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.annotations.task_gate import (
    is_file_compose_only_by_header,
    is_task_compose_only_gated,
)
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-chdir-in-task"

_COMPOSE_CHDIR = re.compile(
    r"chdir:\s*[\"']?\{\{\s*lookup\(\s*['\"]container['\"]\s*,"
    r"\s*application_id\s*,\s*['\"]directories\.instance['\"]\s*\)\s*\}\}"
)


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if "roles/sys-svc-compose/" in rel_path:
        return False
    return rel_path.endswith((".yml", ".yaml")) and (
        "/tasks/" in rel_path or "/handlers/" in rel_path
    )


class TestNoComposeChdirInShellTasks(unittest.TestCase):
    def test_no_compose_chdir_outside_compose_handler(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            if is_suppressed_in_head(lines, _RULE):
                continue
            if is_file_compose_only_by_header(lines):
                continue
            for idx, line in enumerate(lines):
                if not _COMPOSE_CHDIR.search(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                if is_task_compose_only_gated(lines, idx):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found `chdir: ...directories.instance` in shell/command "
                "tasks. That chdir is the compose project root and only "
                "useful for docker-compose-CLI verbs; under swarm there is no "
                "compose project to chdir into.\n\n"
                "Fix patterns by use-case:\n"
                "  - `compose exec` -> `container exec "
                "{{ lookup('container_address', application_id, '<svc>') }} ...`"
                " (drop chdir entirely)\n"
                "  - `compose restart` -> `container service update --force "
                "{{ lookup('container_service', application_id, '<svc>') }}` "
                "for swarm + `compose restart` for compose (split with "
                "`when: DEPLOYMENT_MODE == 'compose'` / `== 'swarm'` blocks)\n"
                "  - one-shot bootstrap via `compose run --profile X` -> deploy "
                "the bootstrap service unconditionally in compose.yml.j2 and, "
                "in swarm, tail `container service logs "
                "{{ lookup('container_service', application_id, '<bootstrap>') }}` "
                "for the result. The compose path keeps the profile + the "
                "compose-run task (gated on `when: DEPLOYMENT_MODE == 'compose'`).\n\n"
                "Mark with `# nocheck: compose-chdir-in-task` only when the role "
                "is intentionally compose-only by design.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
