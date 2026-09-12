"""Lint: a role's meta payload never carries Jinja in a mapping key.

Ansible renders the values of a structure loaded through ``include_vars`` and
leaves its keys alone, so an expression written as a key reaches the consumer
as its own source text. ``web-app-nextcloud``'s sociallogin provider stored

    "groupMapping": {"/{{ lookup('rbac_group_path', ...) }}": "admin"}

in Nextcloud, which matches no group Keycloak ever sends, and the administrator
logging in through OIDC stayed out of the ``admin`` group.

Write the whole mapping as one expression instead, which ``jinja2_native``
returns as a real mapping with the key computed::

    groupMapping: >-
      {{ { '/' ~ lookup('rbac_group_path', ...): 'admin' } }}

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: jinja-mapping-key`` on, or directly above, the offending line.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "jinja-mapping-key"


def _key_before_colon(line: str) -> str:
    stripped = line.strip().removeprefix("- ")
    if not stripped or stripped.startswith(("#", "{{")):
        return ""
    if stripped.startswith(('"', "'")):
        quote = stripped[0]
        end = stripped.find(quote, 1)
        if end == -1 or not stripped[end + 1 :].lstrip().startswith(":"):
            return ""
        return stripped[1:end]
    head, sep, _tail = stripped.partition(":")
    return head if sep else ""


def jinja_mapping_keys() -> list[str]:
    findings = []
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        parts = Path(path).relative_to(PROJECT_ROOT).parts
        if len(parts) < 3 or parts[0] != "roles" or parts[2] != "meta":
            continue
        lines = content.splitlines()
        for number, line in enumerate(lines, start=1):
            if "{{" not in _key_before_colon(line):
                continue
            if is_suppressed_at(lines, number, _RULE):
                continue
            rel = Path(path).relative_to(PROJECT_ROOT)
            findings.append(f"{rel}:{number}: {line.strip()[:80]}")
    return findings


class TestNoJinjaInMappingKeys(unittest.TestCase):
    def test_no_meta_payload_expects_a_key_to_be_rendered(self) -> None:
        findings = jinja_mapping_keys()
        self.assertEqual(
            [],
            findings,
            f"Jinja expression(s) used as a mapping key ({len(findings)}). "
            "Ansible renders the values of an include_vars payload and leaves "
            "the keys as written, so the consumer receives the source text. "
            "Write the whole mapping as one expression instead:\n"
            + "\n".join(f"  - {f}" for f in findings),
        )


if __name__ == "__main__":
    unittest.main()
