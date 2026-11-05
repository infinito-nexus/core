from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.build.docs.header_trust import BEGIN, END, render, replace_block
from cli.build.docs.header_trust.__main__ import main
from utils.roles.mapping import ROLE_FILE_META_SERVICES

HEADERS = {"web-app-a": ["X-Forwarded-User"], "web-app-b": ["X-Remote-User"]}
DECLARATIONS = {
    "web-app-a": {
        "proxy_secret": False,
        "switch": "services.sso.enabled",
        "files": ["files/sso/a.py"],
    },
    "web-app-b": {
        "proxy_secret": "sso_proxy_secret",
        "switch": "x | bool",
        "files": ["templates/env.j2"],
    },
}
EXEMPTIONS = {"web-app-c": [("templates/relay.conf.j2", "reads no header")]}


def _row(text: str, role: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"| `{role}`"))


class TestRender(unittest.TestCase):
    def test_every_detected_role_gets_one_row_with_its_declaration(self) -> None:
        text = render(HEADERS, DECLARATIONS, EXEMPTIONS)
        self.assertEqual(
            "| `web-app-a` | `X-Forwarded-User` | `files/sso/a.py` | no "
            "| `services.sso.enabled` |",
            _row(text, "web-app-a"),
        )
        self.assertIn("| yes, `sso_proxy_secret` |", _row(text, "web-app-b"))

    def test_the_files_column_lists_the_declared_trusting_files(self) -> None:
        moved = {
            **DECLARATIONS,
            "web-app-b": {**DECLARATIONS["web-app-b"], "files": ["files/x.php"]},
        }
        row = _row(render(HEADERS, moved, {}), "web-app-b")
        self.assertIn("| `files/x.php` |", row)
        self.assertNotIn("templates/env.j2", row)

    def test_a_pipe_in_a_switch_does_not_split_the_cell(self) -> None:
        self.assertIn(
            "`x \\| bool`", _row(render(HEADERS, DECLARATIONS, {}), "web-app-b")
        )

    def test_an_exempted_file_is_listed_with_its_reason(self) -> None:
        text = render(HEADERS, DECLARATIONS, EXEMPTIONS)
        self.assertEqual(
            "| `web-app-c` | `templates/relay.conf.j2` | reads no header |",
            _row(text, "web-app-c"),
        )

    def test_no_exemption_renders_no_exemption_table(self) -> None:
        self.assertNotIn("nocheck", render(HEADERS, DECLARATIONS, {}))

    def test_a_changed_declaration_changes_the_render(self) -> None:
        flipped = {
            **DECLARATIONS,
            "web-app-a": {**DECLARATIONS["web-app-a"], "proxy_secret": "s"},
        }
        self.assertIn("| yes, `s` |", _row(render(HEADERS, flipped, {}), "web-app-a"))

    def test_a_detected_role_without_declaration_fails_the_render(self) -> None:
        with self.assertRaises(KeyError):
            render(HEADERS, {"web-app-a": DECLARATIONS["web-app-a"]}, {})


class TestReplaceBlock(unittest.TestCase):
    def test_an_empty_committed_block_is_filled(self) -> None:
        self.assertEqual(
            f"{BEGIN}\n\nfresh\n\n{END}\n", replace_block(f"{BEGIN}\n{END}\n", "fresh")
        )

    def test_missing_markers_raise(self) -> None:
        with self.assertRaises(ValueError):
            replace_block("# no markers\n", "x")


class TestMain(unittest.TestCase):
    def test_main_renders_the_roles_into_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            templates = roles_dir / "web-app-a" / "templates"
            templates.mkdir(parents=True)
            (templates / "proxy.conf.j2").write_text(
                "proxy_set_header X-Remote-User $remote_user;\n", encoding="utf-8"
            )
            services = roles_dir / "web-app-a" / ROLE_FILE_META_SERVICES
            services.parent.mkdir()
            services.write_text(
                "sso:\n  header_trust:\n    proxy_secret: false\n"
                "    switch: services.sso.enabled\n"
                "    files: [templates/proxy.conf.j2]\n",
                encoding="utf-8",
            )
            doc = Path(tmp) / "rbac.md"
            doc.write_text(f"# T\n{BEGIN}\n{END}\n", encoding="utf-8")
            self.assertEqual(
                0, main(["--doc", str(doc), "--roles-dir", str(roles_dir)])
            )
            written = doc.read_text(encoding="utf-8")  # nocheck: cache-read
        self.assertIn(
            "| `web-app-a` | `X-Remote-User` | `templates/proxy.conf.j2` | no "
            "| `services.sso.enabled` |",
            written,
        )


if __name__ == "__main__":
    unittest.main()
