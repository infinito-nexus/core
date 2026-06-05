from __future__ import annotations

import re
import unittest

from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

# New canonical call form: {{ lookup('compose_volumes', application_id, ...) }}
COMPOSE_VOLUMES_LOOKUP_RE = re.compile(r"lookup\(\s*['\"]compose_volumes['\"]\s*,")

# Deprecated pipe form: {{ lookup('applications') | compose_volumes(...) }}
# Forbidden everywhere: the Jinja filter registration was removed so this
# would fail at render time anyway, but the lint catches the regression
# earlier with a clearer message.
DEPRECATED_PIPE_RE = re.compile(r"\|\s*compose_volumes\s*\(")


class TestComposeVolumesCallRequired(unittest.TestCase):
    def test_every_compose_template_calls_compose_volumes(self) -> None:
        roles_dir = PROJECT_ROOT / "roles"
        offenders: list[str] = []

        for compose_template in sorted(roles_dir.glob(f"*/{ROLE_FILE_TEMPL_COMPOSE}")):
            try:
                text = read_text(str(compose_template))
            except UnicodeDecodeError:
                continue
            if COMPOSE_VOLUMES_LOOKUP_RE.search(text):
                continue
            offenders.append(f"- {compose_template.relative_to(PROJECT_ROOT)}")

        if offenders:
            self.fail(
                "Every `templates/compose.yml.j2` MUST call the "
                "`compose_volumes` lookup so the top-level `volumes:` "
                "block is always rendered (empty when no service needs "
                "a volume). Without it, a future variant that flips a "
                "shared service to dedicated mode adds a named-volume "
                "reference in the `services:` block and Docker Compose "
                'fails `config --quiet` with `service "<name>" refers '
                "to undefined volume <name>`. Add "
                "`{{ lookup('compose_volumes', application_id) }}` to "
                "each offending template:\n\n" + "\n".join(offenders)
            )

    def test_no_template_uses_deprecated_pipe_form(self) -> None:
        from pathlib import Path

        roles_prefix = str(PROJECT_ROOT / "roles") + "/"
        offenders: list[str] = []

        for path_str in iter_project_files(extensions=(".j2",)):
            if not path_str.startswith(roles_prefix):
                continue
            if "/templates/" not in path_str:
                continue
            try:
                text = read_text(path_str)
            except UnicodeDecodeError:
                continue
            for m in DEPRECATED_PIPE_RE.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                rel = Path(path_str).relative_to(PROJECT_ROOT)
                offenders.append(f"- {rel}:{line_no}")

        if offenders:
            self.fail(
                "Deprecated `| compose_volumes(...)` pipe form found. "
                "The Jinja filter registration was removed; use the "
                "lookup form instead: "
                "`{{ lookup('compose_volumes', application_id) }}`. "
                "Offending sites:\n\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
