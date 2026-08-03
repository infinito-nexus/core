from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

JINJA_BLOCK_PATTERN = re.compile(r"\{[{%].*?[}%]\}", re.DOTALL)
VARS_KEY_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", re.MULTILINE)
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
KEYWORD_ARGUMENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*=(?!=)")
ATTRIBUTE_OR_FILTER = re.compile(r"[.|]\s*[A-Za-z_][A-Za-z0-9_]*")


def _referenced_names(jinja: str) -> set[str]:
    """Identifiers a Jinja block reads as variables.

    Args:
        jinja: one `{{ ... }}` or `{% ... %}` block.
    """
    for pattern in (STRING_LITERAL, KEYWORD_ARGUMENT, ATTRIBUTE_OR_FILTER):
        jinja = pattern.sub(" ", jinja)
    return set(IDENTIFIER_PATTERN.findall(jinja))


class TestNoRoleVarsInMeta(unittest.TestCase):
    def test_no_role_vars_reference_in_role_meta(self):
        roles_dir = PROJECT_ROOT / "roles"

        role_vars: set[str] = set()
        for vars_file in roles_dir.glob("*/vars/**/*.yml"):
            try:
                role_vars.update(VARS_KEY_PATTERN.findall(read_text(str(vars_file))))
            except OSError:
                continue

        findings: list[tuple[str, int, str, str]] = []
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
                    used = _referenced_names(jinja_match.group(0)) & role_vars
                    if used:
                        findings.append((rel, line_no, min(used), line.strip()))
                        break

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: `{name}`: {snippet}"
                for path, line_no, name, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "`roles/*/vars/` is not bound in the role-meta render context "
                "(the applications registry is built before any role-vars binding, so "
                "the reference stays an unrendered Jinja string and silently yields an "
                "empty value). Inline the literal, or resolve it with "
                "`lookup('config', '<role-id>', ...)` which reads the registry "
                "itself.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
