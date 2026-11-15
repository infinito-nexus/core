from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from plugins.filter.dotenv import dotenv_quote
from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-openwebui/files/python/tool_servers_held.py"
KEY = "held-tool-key-value"
CONNECTIONS = [
    {
        "url": "http://gitea:3000/mcp",
        "type": "mcp",
        "auth_type": "bearer",
        "key": KEY,
        "config": {"enable": True, "access_grants": []},
        "info": {"id": "web-app-gitea", "name": "web-app-gitea"},
    }
]


def _module():
    spec = importlib.util.spec_from_file_location("tool_servers_held", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestToolServersHeld(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.env = Path(self.directory.name) / ".env"
        self.module = _module()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _write(self, value: str) -> None:
        self.env.write_text(
            f"WEBUI_SECRET_KEY=x\nTOOL_SERVER_CONNECTIONS={value}\nOFFLINE_MODE=0\n",
            encoding="utf-8",
        )

    def test_a_compose_quoted_line_gives_only_ids_and_urls(self) -> None:
        self._write(dotenv_quote(json.dumps(CONNECTIONS, separators=(",", ":"))))
        printed = io.StringIO()
        with (
            mock.patch("sys.argv", ["tool_servers_held.py", str(self.env)]),
            mock.patch("sys.stdout", printed),
        ):
            self.module.main()
        self.assertEqual(
            {"web-app-gitea": "http://gitea:3000/mcp"}, json.loads(printed.getvalue())
        )
        self.assertNotIn(KEY, printed.getvalue())

    def test_a_bare_swarm_line_reads_the_same(self) -> None:
        self._write(json.dumps(CONNECTIONS, separators=(",", ":")))
        self.assertEqual(
            {"web-app-gitea": "http://gitea:3000/mcp"},
            self.module.connections(self.env),
        )

    def test_a_file_without_the_variable_holds_no_server(self) -> None:
        self.env.write_text("OFFLINE_MODE=0\n", encoding="utf-8")
        self.assertEqual({}, self.module.connections(self.env))

    def test_a_missing_file_or_a_broken_value_reads_nothing(self) -> None:
        self.assertIsNone(self.module.connections(self.env))
        self._write("not json")
        self.assertIsNone(self.module.connections(self.env))


if __name__ == "__main__":
    unittest.main()
