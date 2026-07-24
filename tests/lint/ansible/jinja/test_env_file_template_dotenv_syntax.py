"""Flag env-file template lines written in YAML mapping syntax
(``KEY: value``) instead of dotenv assignment syntax (``KEY=value``).

env.j2 templates are rendered and mounted as a Docker ``env_file``. docker
compose's lenient godotenv parser tolerates ``KEY: value`` (it splits on the
first ``=`` and, finding none, has historically accepted the colon form), but
``docker stack deploy`` uses the strict CLI kvfile reader which requires
``KEY=value`` and rejects a colon line with "variable ... contains
whitespaces", aborting the swarm deploy.

Allowed forms for a data line:

* ``KEY=value`` / ``KEY={{ ... }}`` (dotenv assignment)
* ``# comment`` and blank lines
* Jinja control (``{% ... %}``) and Jinja comments (``{# ... #}``)

Rejected: ``KEY: value``, ``KEY: "{{ ... }}"`` (YAML mapping syntax).

Per-line opt-out: ``# nocheck: env-file-dotenv-syntax`` on the offending line
or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "env-file-dotenv-syntax"

_YAML_COLON_ASSIGN = re.compile(r"^\s*[A-Z][A-Z0-9_]*\s*:\s*\S")


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if "/templates/" not in rel_path:
        return False
    if not rel_path.endswith(".j2"):
        return False
    base = Path(rel_path).name
    return ".env" in base or base.endswith("env.j2")


class TestEnvFileTemplateDotenvSyntax(unittest.TestCase):
    def test_env_templates_use_dotenv_assignment_syntax(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _YAML_COLON_ASSIGN.match(line):
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
                "Found env-file template lines in YAML mapping syntax "
                "(`KEY: value`). docker stack deploy's kvfile reader requires "
                "`KEY=value` and rejects the colon form, aborting the swarm "
                "deploy (compose's lenient parser hides it).\n\n"
                "Fix: use `KEY=value` (env-file syntax allows spaces unquoted; "
                "use `KEY={{ ... | dotenv_quote }}` for values with shell "
                "metachars / dollars). Mark with `# nocheck: env-file-dotenv-"
                "syntax` only when the consumer genuinely needs the colon "
                "form (very rare).\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
