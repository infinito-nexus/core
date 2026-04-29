from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import yaml

import cli.meta.domains.__main__ as mod


class TestCliMetaApplicationsDomains(TestCase):
    def write_role(
        self, roles_dir: Path, role_name: str, app_id: str, config: dict
    ) -> None:
        role_dir = roles_dir / role_name
        (role_dir / "vars").mkdir(parents=True, exist_ok=True)
        (role_dir / "meta").mkdir(parents=True, exist_ok=True)
        (role_dir / "vars" / "main.yml").write_text(
            yaml.safe_dump({"application_id": app_id}, sort_keys=False),
            encoding="utf-8",
        )
        server_payload = config.get("server", {}) if isinstance(config, dict) else {}
        (role_dir / "meta" / "server.yml").write_text(
            yaml.safe_dump(server_payload, sort_keys=False),
            encoding="utf-8",
        )

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            try:
                with patch("sys.argv", ["prog", *argv]):
                    mod.main()
                return 0, out.getvalue(), err.getvalue()
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
                return code, out.getvalue(), err.getvalue()

    def test_cli_supports_alias_and_www_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            roles_dir.mkdir()
            self.write_role(
                roles_dir,
                "web-app-dashboard",
                "web-app-dashboard",
                {
                    "server": {
                        "domains": {
                            "canonical": ["dashboard.{{ DOMAIN_PRIMARY }}"],
                            "aliases": ["alias.{{ DOMAIN_PRIMARY }}"],
                        }
                    }
                },
            )

            with patch.object(mod.domain_list, "ROLES_DIR", roles_dir):
                code, out, err = self._run(
                    [
                        "--domain-primary",
                        "infinito.example",
                        "--alias",
                        "--www",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out.strip().splitlines(),
            [
                "alias.infinito.example",
                "dashboard.infinito.example",
                "test.infinito.example",
                "www.alias.infinito.example",
                "www.dashboard.infinito.example",
                "www.test.infinito.example",
            ],
        )


if __name__ == "__main__":
    main()
