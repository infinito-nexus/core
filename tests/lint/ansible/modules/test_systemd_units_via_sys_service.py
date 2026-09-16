"""Lint: a systemd unit is installed through sys-service, not by hand.

``sys-service`` owns what it takes to make a unit real: resolving the template,
writing it into the system unit directory, reloading the daemon, enabling and
starting it, the timer variant, and the async and flush behaviour the deploy
relies on. A role that renders its own ``*.service.j2`` with a bare ``template:``
gets the file and none of the rest, and every one of those omissions is silent —
a unit that exists but was never enabled looks installed until the host reboots.

It is also how the same decisions end up answered differently per role. That is
not hypothetical: the role this lint was written alongside rendered its own unit
and its own reload handler before anyone noticed sys-service already did both.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: systemd-via-sys-service`` on the ``src:`` line or anywhere in the
  task body, for a unit sys-service genuinely cannot carry.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "systemd-via-sys-service"
_OWNER = "sys-service"
_UNIT_SRC = re.compile(r"^\s*src:\s*[\"']?(?P<src>[^\"'\s]+\.service\.j2)[\"']?")


def _is_task_file(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/tasks/" in rel_path
        and rel_path.endswith((".yml", ".yaml"))
    )


def _role_of(rel_path: str) -> str:
    return Path(rel_path).parts[1]


class TestSystemdUnitsViaSysService(unittest.TestCase):
    def test_no_role_installs_its_own_unit(self) -> None:
        findings: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_task_file(rel) or _role_of(rel) == _OWNER:
                continue
            lines = content.splitlines()
            for index, line in enumerate(lines):
                match = _UNIT_SRC.match(line)
                if match is None:
                    continue
                if is_suppressed_at(lines, index + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append(f"- {rel}:{index + 1}: {match.group('src')}")

        if findings:
            self.fail(
                "These roles render a systemd unit themselves instead of handing "
                "it to sys-service, which also reloads the daemon, enables the "
                "unit, and carries the timer, async and flush behaviour:\n"
                + "\n".join(sorted(set(findings)))
                + "\n\nFix: name the template templates/systemctl.service.j2 and "
                "include the sys-service role with system_service_id, or mark the "
                f"task `# nocheck: {_RULE}` when sys-service cannot carry it."
            )


if __name__ == "__main__":
    unittest.main()
