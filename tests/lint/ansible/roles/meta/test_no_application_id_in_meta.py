from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

JINJA_BLOCK_PATTERN = re.compile(r"\{[{%].*?[}%]\}", re.DOTALL)
APPLICATION_ID_AS_VARIABLE = re.compile(r"\bapplication_id\b(?!\s*=[^=])")


class TestNoApplicationIdInMeta(unittest.TestCase):
    def test_no_application_id_reference_in_role_meta(self):
        roles_dir = PROJECT_ROOT / "roles"
        findings: list[tuple[str, int, str]] = []

        for meta_file in roles_dir.glob("*/meta/*.yml"):
            try:
                content = read_text(str(meta_file))
            except OSError:
                continue
            rel = meta_file.relative_to(PROJECT_ROOT).as_posix()
            for line_no, line in enumerate(content.splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                for jinja_match in JINJA_BLOCK_PATTERN.finditer(line):
                    if APPLICATION_ID_AS_VARIABLE.search(jinja_match.group(0)):
                        findings.append((rel, line_no, line.strip()))
                        break

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "`application_id` is not bound in the role-meta render context "
                "(the applications registry is built before any role-vars binding, "
                "so `lookup('config', application_id, ...)` returns the raw "
                "unrendered Jinja string instead of the resolved value). "
                "Spell out the role id explicitly (e.g. `'web-app-nextcloud'`) "
                "instead of relying on `application_id` in `roles/*/meta/*.yml`.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
