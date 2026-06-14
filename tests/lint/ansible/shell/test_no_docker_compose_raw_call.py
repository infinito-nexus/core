"""Flag raw ``docker compose <verb>`` (plugin form) calls in shell or
command tasks. They are docker-compose-CLI-only and bypass the
``BIN_COMPOSE`` SPOT and the ``container`` wrapper.

Per-line opt-out: ``# nocheck: docker-compose-raw-call`` on the
offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "docker-compose-raw-call"

_DOCKER_COMPOSE = re.compile(
    r"\bdocker\s+compose\s+(?:exec|run|restart|logs|up|down|ps|config|build|pull|stop|start|rm|kill)\b"
)


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if "roles/sys-svc-compose/" in rel_path:
        return False
    return rel_path.endswith((".yml", ".yaml")) and (
        "/tasks/" in rel_path or "/handlers/" in rel_path
    )


class TestNoDockerComposeRawCall(unittest.TestCase):
    def test_no_raw_docker_compose_outside_compose_handler(self) -> None:
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
                if not _DOCKER_COMPOSE.search(line):
                    continue
                if line.lstrip().startswith("#"):
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
                "Found raw `docker compose <verb>` calls (plugin form). "
                "Use the BIN_COMPOSE constant for compose verbs and the "
                "`container` wrapper for everything else.\n\n"
                "Fix: replace `docker compose <verb> ...` with "
                "`{{ BIN_COMPOSE }} <verb> ...` and gate behind "
                "`when: DEPLOYMENT_MODE != 'swarm'` because compose verbs "
                "don't work under `docker stack deploy`. For inspect/exec "
                "use `container <verb>` via the wrapper. Mark with "
                "`# nocheck: docker-compose-raw-call` only for compose-only "
                "diagnostic scripts.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
