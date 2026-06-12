"""Flag `compose <verb>` / `{{ BIN_COMPOSE }} <verb>` calls in shell or command
tasks. These verbs are docker-compose-CLI-only and break under
`docker stack deploy`, where there is no compose project, no profiles,
and no `condition: service_healthy` semantics. Rollen die solche Calls
nutzen sind nicht swarm-kompatibel ohne expliziten swarm-Branch.

Per-line opt-out: ``# nocheck: compose-verb-in-task`` on the offending
line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-verb-in-task"

_COMPOSE_VERB = re.compile(
    r"\{\{\s*BIN_COMPOSE\s*\}\}\s+(?:exec|run|restart|logs|up|down|ps|config)\b"
    r"|(?<![\w.-])compose\s+(?:exec|run|restart|logs|up|down|ps|config)\b"
)
# Exclude Ansible handler triggers (`notify: compose up`) and comment lines.
_HANDLER_TRIGGER = re.compile(r"^\s*notify\s*:")
_COMMENT_LINE = re.compile(r"^\s*#")


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if "roles/sys-svc-compose/" in rel_path:
        return False
    return rel_path.endswith((".yml", ".yaml")) and (
        "/tasks/" in rel_path or "/handlers/" in rel_path
    )


class TestNoComposeVerbInShellTasks(unittest.TestCase):
    def test_no_compose_verb_outside_compose_handler(self) -> None:
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
                if _COMMENT_LINE.match(line) or _HANDLER_TRIGGER.match(line):
                    continue
                if not _COMPOSE_VERB.search(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found `compose <verb>` / `{{ BIN_COMPOSE }} <verb>` calls in "
                "shell/command tasks. These verbs are docker-compose-CLI-only "
                "and break under `docker stack deploy` (no compose project, "
                "no profiles, no service_healthy depends_on).\n\n"
                "Fix: replace with `container <verb>` via the wrapper and use "
                "`lookup('container_address', ...)` / `lookup('container_service', ...)` "
                "for the target. If the call is legitimately compose-only, wrap it "
                "in a block gated by `when: DEPLOYMENT_MODE != 'swarm'` and add a "
                "swarm-equivalent alongside, OR mark with "
                "`# nocheck: compose-verb-in-task` if the role itself is "
                "compose-only by design.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
