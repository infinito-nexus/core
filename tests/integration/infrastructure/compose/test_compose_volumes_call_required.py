from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

COMPOSE_VOLUMES_CALL_RE = re.compile(r"\|\s*compose_volumes\s*\(")


class TestComposeVolumesCallRequired(unittest.TestCase):
    def test_every_compose_template_calls_compose_volumes(self) -> None:
        roles_dir = PROJECT_ROOT / "roles"
        offenders: list[str] = []

        for compose_template in sorted(roles_dir.glob("*/templates/compose.yml.j2")):
            try:
                text = read_text(str(compose_template))
            except UnicodeDecodeError:
                continue
            if COMPOSE_VOLUMES_CALL_RE.search(text):
                continue
            offenders.append(f"- {compose_template.relative_to(PROJECT_ROOT)}")

        if offenders:
            self.fail(
                "Every `templates/compose.yml.j2` MUST call the "
                "`compose_volumes` filter so the top-level `volumes:` "
                "block is always rendered (empty when no service needs "
                "a volume). Without it, a future variant that flips a "
                "shared service to dedicated mode adds a named-volume "
                "reference in the `services:` block and Docker Compose "
                'fails `config --quiet` with `service "<name>" refers '
                "to undefined volume <name>`. Add "
                "`{{ lookup('applications') | compose_volumes("
                "application_id) }}` to each offending template:\n\n"
                + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
