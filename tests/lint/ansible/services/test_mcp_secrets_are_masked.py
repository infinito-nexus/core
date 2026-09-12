"""Lint: an MCP task that prints cannot carry a secret unmasked.

Ansible echoes a command module's arguments and its shell environment once the
run is verbose, which is how a provisioning password ends up in a deploy log
verbatim. A task only leaks if it does both things: handle a secret value and
produce output Ansible prints. A ``set_fact`` or an include that forwards a
variable prints nothing at default verbosity.

Masking is satisfied by ``no_log`` or, for modules that mask their own payload,
``mask_values``. Both are expected to reference ``MASK_CREDENTIALS_IN_LOGS``
rather than a literal, which ``tests/lint/ansible/modules/test_no_literal_no_log.py``
enforces separately.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-secret-masking`` on, or directly above, the task's ``- name:``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

_RULE = "mcp-secret-masking"

_SECRET_RE = re.compile(
    r"token|password|bearer|api_key|secret|credential|authoriz|auth_header",
    re.IGNORECASE,
)
_PRINTS_RE = re.compile(
    r"ansible\.builtin\.(command|shell|uri|debug)|"
    r"^\s+(command|shell|uri|debug):|register:",
    re.MULTILINE,
)
_MASKED_RE = re.compile(r"^\s+(no_log|mask_values)\s*:", re.MULTILINE)


def _mcp_task_files() -> list[tuple[str, str]]:
    """Return ``(path, content)`` for every MCP task file under ``roles/``."""
    files = []
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        parts = Path(path).parts
        if "roles" not in parts or "tasks" not in parts:
            continue
        if "mcp" not in Path(path).stem and not any("mcp" in part for part in parts):
            continue
        files.append((path, content))
    return files


def unmasked_secret_tasks() -> list[str]:
    """Return one finding per printing MCP task that carries a secret unmasked."""
    findings = []
    for path, content in _mcp_task_files():
        lines = content.splitlines()
        offset = 0
        for block in re.split(r"^(?=- name:)", content, flags=re.MULTILINE):
            start = offset
            offset += block.count("\n")
            if not block.startswith("- name:"):
                continue
            if not _SECRET_RE.search(block) or not _PRINTS_RE.search(block):
                continue
            if _MASKED_RE.search(block):
                continue
            if is_suppressed_at(lines, start + 1, _RULE):
                continue
            findings.append(
                f"{path}:{start + 1}: {block.splitlines()[0][8:70]} handles a "
                f"secret and prints, but carries neither no_log nor mask_values"
            )
    return findings


class TestMcpSecretsAreMasked(unittest.TestCase):
    def test_no_printing_mcp_task_carries_a_secret_unmasked(self) -> None:
        findings = unmasked_secret_tasks()
        self.assertEqual(
            [],
            findings,
            f"MCP task(s) that can print a secret ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reaches_the_mcp_task_files(self) -> None:
        self.assertTrue(
            _mcp_task_files(),
            "no MCP task file was scanned, so the rule would pass vacuously",
        )

    def test_the_scan_reaches_the_adapter_that_holds_every_provider_credential(
        self,
    ) -> None:
        """The non-empty guard above passed while this role was invisible.

        `svc-ai-mcp-adapter` is the one role whose whole job is handling other
        roles' MCP credentials, and its directory name contains `mcp` without
        being equal to it, so a membership test over the path parts skipped it
        and the provider roles kept the scan looking populated.
        """
        scanned = {path for path, _ in _mcp_task_files()}
        self.assertTrue(
            any("svc-ai-mcp-adapter/tasks/" in path for path in scanned),
            "svc-ai-mcp-adapter task files are outside the scan",
        )


if __name__ == "__main__":
    unittest.main()
