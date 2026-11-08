from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from cli.build.docs.readme.generate import generate_readme
from utils.roles.mapping import (
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "web-app-sample"
READS_COUNTRY = 'SAMPLE_COUNTRY: "{{ service_provider.company.address.country }}"\n'
COUNTRY_VARS = (
    '\\"service_provider\\": {\\"company\\": {\\"address\\": '
    '{\\"country\\": \\"$COUNTRY\\"}}}, '
)


def _production_block(files: dict[str, str]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        role_dir = Path(tmp) / ROLE
        for rel, content in files.items():
            path = role_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        text, _ = generate_readme(role_dir, ROLE)
    return text.split("### Production", 1)[1].split("## Credits", 1)[0]


class TestServiceProviderCountry(unittest.TestCase):
    def test_stack_role_reading_the_country_in_vars_asks_for_it(self) -> None:
        block = _production_block(
            {ROLE_FILE_TEMPL_COMPOSE: "", ROLE_FILE_VARS_MAIN: READS_COUNTRY}
        )

        self.assertIn('COUNTRY="<your-country>"', block)
        self.assertIn('-e COUNTRY="$COUNTRY"', block)
        self.assertIn(COUNTRY_VARS, block)

    def test_role_reading_the_country_in_tasks_asks_for_it(self) -> None:
        block = _production_block(
            {ROLE_FILE_TEMPL_COMPOSE: "", ROLE_FILE_TASKS_MAIN: READS_COUNTRY}
        )

        self.assertIn('COUNTRY="<your-country>"', block)
        self.assertIn(COUNTRY_VARS, block)

    def test_host_role_reading_the_country_asks_for_it(self) -> None:
        block = _production_block({ROLE_FILE_VARS_MAIN: READS_COUNTRY})

        self.assertIn("--host localhost", block)
        self.assertIn('COUNTRY="<your-country>"', block)
        self.assertIn(COUNTRY_VARS, block)

    def test_the_production_commands_parse_as_bash(self) -> None:
        for files in (
            {ROLE_FILE_TEMPL_COMPOSE: "", ROLE_FILE_VARS_MAIN: READS_COUNTRY},
            {ROLE_FILE_VARS_MAIN: READS_COUNTRY},
        ):
            block = _production_block(files)
            scripts = re.findall(r"```bash\n(.*?)```", block, re.DOTALL)
            self.assertTrue(scripts)
            for script in scripts:
                checked = subprocess.run(
                    ["bash", "-n"],
                    input=script,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_role_rendering_the_country_only_in_a_template_does_not_ask(
        self,
    ) -> None:
        block = _production_block(
            {
                ROLE_FILE_TEMPL_COMPOSE: "",
                "templates/imprint.html.j2": READS_COUNTRY,
            }
        )

        self.assertNotIn("COUNTRY", block)
        self.assertNotIn("service_provider", block)


if __name__ == "__main__":
    unittest.main()
