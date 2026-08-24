"""Forbid hand-written ``extra_hosts:`` blocks in role templates.

``extra_hosts`` is the one compose key a service may not carry twice. The
``container_extra_hosts`` lookup emits it for the SSO back-channel on onion
deployments, so a template that also writes the key by hand puts it into the
same mapping a second time. YAML then either rejects the document or keeps one
list and drops the other, and the loser is silent.

Routing every pin through the lookup removes that failure mode by construction
and hands the caller the deploy-mode decision for free: Docker resolves the
magic ``host-gateway`` value under compose but not under swarm, where a node
address is required.

    {{ lookup('container_extra_hosts',
              extra_hosts=['host.docker.internal:host-gateway']) | indent(4) }}

A role whose entries need real logic builds the list in its own lookup and
passes the constant, the way ``web-app-mailu`` does with ``MAILU_EXTRA_HOSTS``
(``roles/web-app-mailu/lookup_plugins/mailu_extra_hosts.py``).

Per-line opt-out: ``# nocheck: compose-extra-hosts-use-lookup`` on the offending
line or the immediately preceding non-empty line. Use it only when the block
genuinely cannot route through the lookup, and say why -- a second literal
block is a duplicate-key hazard for every other pin the same service receives.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-extra-hosts-use-lookup"

_EXTRA_HOSTS_KEY = re.compile(r"\Aextra_hosts\s*:")


def _is_scan_target(rel_path: str) -> bool:
    """A template under a role that renders compose/stack YAML.

    Args:
        rel_path: repository-relative path of the candidate file.
    """
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith(".yml.j2")
    )


def _collect_findings() -> list[tuple[str, int]]:
    findings: list[tuple[str, int]] = []
    for path_str, content in iter_project_files_with_content(
        extensions=(".j2",),
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not _is_scan_target(rel):
            continue
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            if not _EXTRA_HOSTS_KEY.match(line.strip()):
                continue
            if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                continue
            findings.append((rel, idx + 1))
    return sorted(set(findings))


class TestComposeExtraHostsUseLookup(unittest.TestCase):
    def test_no_hand_written_extra_hosts_block(self) -> None:
        findings = _collect_findings()
        if not findings:
            return

        formatted = "\n".join(f"- {rel}:{line_no}" for rel, line_no in findings)
        self.fail(
            "Found hand-written `extra_hosts:` blocks in role templates. The "
            "container_extra_hosts lookup also emits this key for the SSO "
            "back-channel, so a second literal block duplicates the mapping key "
            "and one of the two lists is silently dropped. Pass the entries to "
            "the lookup instead, which emits the key exactly once and picks the "
            "right address per deploy mode:\n\n"
            "    {{ lookup('container_extra_hosts',\n"
            "              extra_hosts=['name:address']) | indent(4) }}\n\n"
            f"Affected templates:\n{formatted}\n\n"
            f"Per-line opt-out: `# nocheck: {_RULE}` with a reason."
        )


if __name__ == "__main__":
    unittest.main()
