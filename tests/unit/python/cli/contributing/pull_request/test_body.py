from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from jinja2 import UndefinedError

from cli.contributing.pull_request.body import (
    TEMPLATE,
    TemplateError,
    areas,
    environment,
    markdown_table,
    render,
    variables,
)
from cli.meta.ci.subset_roles import extract_roles
from utils.cache.files import read_text

SCORE_ARGS = (
    "--fix",
    "92",
    "--break",
    "3",
    "--efficiency",
    "-",
    "--speed",
    "-",
    "--security",
    "100",
    "--critical",
    "0",
)
SCORE_TABLE = (
    "| 🎯 Fix | 💥 Break | 💸 Tokens | ⏱️ Velocity | 🛡️ Security | 🏆 Score | Gate |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
    "| 92 % | 3 % | – | – | 100 % | 89 | ✅ 90/5, tokens and velocity <= 100, security 100 % |"
)
MESSAGE_BLOCK = (
    "🎯 Fix: 92 %\n"
    "💥 Break: 3 %\n"
    "💸 Tokens: –\n"
    "⏱️ Velocity: –\n"
    "🛡️ Security: 100 %\n"
    "🏆 Score: 89\n"
    "🚦 Gate: ✅ 90/5, tokens and velocity <= 100, security 100 %"
)
SCORE_SCRIPT = (
    Path.home() / ".claude" / "skills" / "kvb-check-score" / "scripts" / "score.py"
)
FORMER_TYPES = (
    "agents",
    "documentation",
    "pipeline",
    "server",
    "system",
    "workstation",
)
SUBSET_ROLES = {
    "pipeline": ["sys-version"],
    "server": ["web-app-nextcloud"],
    "system": ["sys-version"],
    "workstation": ["dsk-firefox"],
}


def values(scope: str) -> dict:
    area = areas()[scope]
    return {
        "audience": "agent",
        "scope": scope,
        "title": f"feat({scope}): render the body from the template",
        "summary": "The body is rendered from one template.",
        "closes": [12, 34],
        "intent": "feature",
        "components": ["cli/contributing/pull_request/body.py"],
        "integrations": area["integrations"][:1],
        "files": [row[0] for row in area["files"][:1]],
        "roles": SUBSET_ROLES.get(scope, []),
        "semver": "minor",
        "details": "One source, one renderer.",
        "checks": [area["checks"][0][0]],
        "evidence": "pytest tests/unit/python/cli/contributing/pull_request: 1 passed",
        "security_impact": False,
        "security_notes": None,
        "review_focus": ["The area data in the template."],
        "score_table": SCORE_TABLE,
        "dod": True,
        "notes": "None.",
    }


def section(body: str, heading: str) -> str:
    return body.split(f"\n## {heading}\n\n", 1)[1].split("\n\n## ", 1)[0]


class TestRenderPerFormerType(unittest.TestCase):
    def test_every_former_type_is_an_area(self) -> None:
        self.assertLessEqual(set(FORMER_TYPES), set(areas()))

    def test_each_type_renders_its_own_checks_and_values(self) -> None:
        for scope in FORMER_TYPES:
            with self.subTest(scope=scope):
                area = areas()[scope]
                body = render(values(scope))
                self.assertTrue(
                    body.startswith(
                        f"# feat({scope}): render the body from the template\n"
                    )
                )
                self.assertIn(f"## {area['affected']}\n", body)
                self.assertIn(f"- [x] {area['checks'][0][1]}\n", body)
                self.assertIn("Closes #12\nCloses #34\n", body)
                self.assertIn(f"- [x] **Feature** - {area['feature']}\n", body)
                self.assertNotIn("{{", body)
                self.assertNotIn("{%", body)
                self.assertNotIn("Examples:", body)
                self.assertNotIn("Explain what changed and why", body)

    def test_each_type_fails_loudly_on_a_missing_required_variable(self) -> None:
        for scope in FORMER_TYPES:
            for name in ("summary", "score_table", "evidence"):
                with self.subTest(scope=scope, name=name):
                    broken = values(scope)
                    del broken[name]
                    with self.assertRaisesRegex(
                        TemplateError, f"missing template variable.*{name}"
                    ):
                        render(broken)
                    with self.assertRaises(UndefinedError):
                        environment().from_string(read_text(str(TEMPLATE))).render(
                            **broken
                        )

    def test_each_type_fails_loudly_on_an_empty_required_text(self) -> None:
        for scope in FORMER_TYPES:
            with self.subTest(scope=scope):
                broken = values(scope)
                broken["summary"] = None
                with self.assertRaisesRegex(TemplateError, "summary is required"):
                    render(broken)

    def test_a_check_of_another_area_fails(self) -> None:
        broken = values("documentation")
        broken["checks"] = ["login"]
        with self.assertRaisesRegex(
            TemplateError, "checks of scope documentation has no login"
        ):
            render(broken)

    def test_an_unknown_variable_fails(self) -> None:
        broken = values("server")
        broken["sumary"] = "typo"
        with self.assertRaisesRegex(TemplateError, "unknown template variable.*sumary"):
            render(broken)

    def test_subset_roles_reach_the_ci_parser(self) -> None:
        for scope, roles in SUBSET_ROLES.items():
            with self.subTest(scope=scope):
                self.assertEqual(extract_roles(render(values(scope))), roles)

    def test_server_renders_integrations_and_file_rows(self) -> None:
        body = render(values("server"))
        self.assertIn("- [x] Dashboard\n- [ ] Matomo\n", body)
        self.assertIn("| [x] | `README.md` |", body)

    def test_agents_and_documentation_carry_no_subset_block(self) -> None:
        for scope in ("agents", "documentation"):
            with self.subTest(scope=scope):
                self.assertNotIn("```yaml", render(values(scope)))


class TestScoreBlock(unittest.TestCase):
    def test_the_rendered_score_block_is_a_markdown_table(self) -> None:
        rows = markdown_table(section(render(values("system")), "Score"))
        self.assertEqual(rows[0][0], "🎯 Fix")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), len(rows[1]))

    def test_the_score_table_is_embedded_verbatim(self) -> None:
        self.assertIn(f"## Score\n\n{SCORE_TABLE}\n", render(values("pipeline")))

    def test_the_commit_message_form_is_refused_as_a_table(self) -> None:
        broken = values("server")
        broken["score_table"] = MESSAGE_BLOCK
        with self.assertRaises(TemplateError):
            render(broken)

    def test_a_ragged_table_is_refused(self) -> None:
        with self.assertRaisesRegex(TemplateError, "differ in width"):
            markdown_table("| a | b |\n| --- | --- |\n| 1 |")

    @unittest.skipUnless(
        SCORE_SCRIPT.is_file(), "kvb-check-score is not installed on this host"
    )
    def test_the_commit_message_form_is_unchanged(self) -> None:
        def score(layout: str) -> str:
            return subprocess.run(
                [sys.executable, str(SCORE_SCRIPT), *SCORE_ARGS, layout],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.rstrip("\n")

        self.assertEqual(score("--message-block"), MESSAGE_BLOCK)
        self.assertEqual(score("--table"), SCORE_TABLE)


class TestContract(unittest.TestCase):
    def test_the_variable_set_is_the_documented_one(self) -> None:
        self.assertEqual(variables(), frozenset(values("general")))


if __name__ == "__main__":
    unittest.main()
