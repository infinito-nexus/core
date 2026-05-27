# tests/integration/test_env_passwords_quoted.py
#
# Integration test: ensure all password-like assignments in env.j2 templates
# that are variable-derived (Jinja) are:
#   1) a PURE Jinja expression (no surrounding quotes in the template)
#   2) use the `| dotenv_quote` filter
#
# Rationale:
#   The `dotenv_quote` filter RETURNS a fully double-quoted string. Therefore
#   templates MUST NOT wrap it in additional quotes, or double-quoting occurs.
#
# Ignored:
# - literals without Jinja (e.g. REDIS_PASSWORD=null)
#
# Required form:
#   SOME_PASSWORD={{ some_password_var | dotenv_quote }}
#
# Forbidden (would double-quote):
#   SOME_PASSWORD="{{ some_password_var | dotenv_quote }}"
#
# Run:
#   python -m unittest -v tests.integration.test_env_passwords_quoted
#
from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

PASSWORD_ASSIGN_RE = re.compile(
    r"""^
        (?P<indent>\s*)
        (?P<key>[A-Za-z_][A-Za-z0-9_]*password[A-Za-z0-9_]*)
        (?P<ws1>\s*)=(?P<ws2>\s*)
        (?P<rhs>.*?)
        (?P<trail>\s*)
        $
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Exactly: {{ ... }}
JINJA_PURE_RE = re.compile(r"^\{\{\s*(?P<expr>.+?)\s*\}\}$")

# Exactly: "{{ ... }}"  (FORBIDDEN - would double-quote because dotenv_quote already quotes)
JINJA_DOUBLE_WRAPPED_RE = re.compile(r'^"\{\{\s*(?P<expr>.+?)\s*\}\}"$')

DOTENV_FILTER = "dotenv_quote"


def _is_full_line_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_jinja_control_line(line: str) -> bool:
    s = line.lstrip()
    return s.startswith(("{%", "{#"))


class TestEnvPasswordsQuotedAndFiltered(unittest.TestCase):
    def test_password_env_vars_are_dotenv_quoted_without_double_quoting(self):
        root = PROJECT_ROOT
        env_templates = sorted(
            Path(p)
            for p in iter_project_files(extensions=(".j2",))
            if Path(p).name == "env.j2"
        )

        failures: list[str] = []

        for path in env_templates:
            rel = path.relative_to(root)
            try:
                lines = read_text(str(path)).splitlines()
            except (OSError, UnicodeDecodeError):
                continue

            for lineno, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                if _is_full_line_comment(line):
                    continue
                if _is_jinja_control_line(line):
                    continue

                m = PASSWORD_ASSIGN_RE.match(line)
                if not m:
                    continue

                key = m.group("key")
                rhs = m.group("rhs").strip()

                # Only enforce rules when value is variable-derived (Jinja present)
                if "{{" not in rhs or "}}" not in rhs:
                    continue

                # Explicitly forbid: "{{ ... }}" (double-quoting in templates)
                if JINJA_DOUBLE_WRAPPED_RE.match(rhs):
                    failures.append(
                        f"{rel}:{lineno}: {key} is wrapped in double quotes, which would cause double-quoting.\n"
                        f'  Forbidden: "{{{{ ... | {DOTENV_FILTER} }}}}"\n'
                        f"  Required:  {{{{ ... | {DOTENV_FILTER} }}}}\n"
                        f"  Found:     {rhs!r}"
                    )
                    continue

                # Must be exactly a pure Jinja expression: {{ ... }}
                m_jinja = JINJA_PURE_RE.match(rhs)
                if not m_jinja:
                    failures.append(
                        f"{rel}:{lineno}: {key} must be a pure Jinja expression (no surrounding quotes).\n"
                        f"  Required:  {{{{ ... | {DOTENV_FILTER} }}}}\n"
                        f"  Found:     {rhs!r}"
                    )
                    continue

                expr = m_jinja.group("expr")

                # Must contain dotenv_quote filter
                if DOTENV_FILTER not in expr:
                    failures.append(
                        f"{rel}:{lineno}: {key} is missing '| {DOTENV_FILTER}'.\n"
                        f"  Required:  {{{{ ... | {DOTENV_FILTER} }}}}\n"
                        f"  Found:     {rhs!r}"
                    )

        if failures:
            self.fail(
                "Invalid password definitions found in env.j2 templates.\n\n"
                "Rules:\n"
                f"  - password variables must be a pure Jinja expression: {{{{ ... }}}}\n"
                f"  - password variables must use '| {DOTENV_FILTER}'\n"
                f"  - wrapping Jinja in double quotes is forbidden (prevents double-quoting)\n"
                "  - literals (no Jinja) are ignored\n\n"
                "Failures:\n- " + "\n- ".join(failures)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
