"""Scheduler services in role ``meta/services.yml`` MUST set ``replicas: 1``.

Rationale
=========
A scheduler (cron, clock, celery ``beat``, a framework ``scheduler`` process)
enqueues recurring jobs. Running more than one replica means several schedulers
fire the same jobs at the same tick, which is never useful and actively harmful:
duplicate work, lock contention, and unique-index collisions (e.g. GoodJob's
``(cron_key, cron_at)`` index). On swarm the default replica count is
``len(hosts)`` (see ``plugins/lookup/compose_replicas.py``), so a scheduler with
no explicit ``replicas`` silently fans out to one-per-node.

Worker services (``sidekiq``, ``worker``, ``queue``) are intentionally NOT
matched: they process jobs and are meant to scale horizontally.

Per-service opt-out
===================
Add ``# nocheck: scheduler-single-replica`` on the service-key line or the
immediately preceding non-empty line, with a comment explaining why more than
one replica is safe for that specific service.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

_RULE = "scheduler-single-replica"

_SCHEDULER_KEY = re.compile(r"^(.*-)?(cron|scheduler|beat|clock)$")


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/meta/" in rel_path
        and rel_path.endswith("services.yml")
    )


class TestSchedulerSingleReplica(unittest.TestCase):
    def test_scheduler_services_pin_single_replica(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            try:
                data = load_yaml_str(content)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            lines = content.splitlines()
            for key, val in data.items():
                if not isinstance(key, str) or not _SCHEDULER_KEY.match(key):
                    continue
                if isinstance(val, dict) and val.get("replicas") == 1:
                    continue
                idx = next(
                    (
                        i
                        for i, line in enumerate(lines)
                        if re.match(rf"^{re.escape(key)}\s*:", line)
                    ),
                    None,
                )
                if idx is not None and is_suppressed_at(
                    lines, idx + 1, _RULE, mode="same-or-above"
                ):
                    continue
                findings.append((rel, (idx or 0) + 1, key))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: service '{k}' must set `replicas: 1`"
                for p, n, k in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found scheduler services in role meta/services.yml without "
                "`replicas: 1`. A scheduler must run as a single replica; on "
                "swarm the default replica count is `len(hosts)`, so several "
                "schedulers would fire the same recurring jobs and collide "
                "(duplicate work, lock contention, unique-index violations).\n\n"
                "Fix: add `replicas: 1` to the service. If more than one replica "
                "is genuinely safe, add `# nocheck: scheduler-single-replica` "
                "with a one-line justification.\n\n"
                f"Offending services:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
