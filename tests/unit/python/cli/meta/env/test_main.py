from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli.meta.env.__main__ as env_main


class TestDotenvHostOwned(unittest.TestCase):
    def _run(self, *, dotenv_exists: bool, host_owned: str | None) -> tuple[int, bool]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "default.env").write_text("INFINITO_DISTRO=debian\n")
            if dotenv_exists:
                (root / ".env").write_text("INFINITO_RUNNING_ON_GITHUB=true\n")
            environ = (
                {} if host_owned is None else {env_main.HOST_OWNED_KEY: host_owned}
            )
            with (
                patch.object(env_main, "REPO_ROOT", root),
                patch.dict("os.environ", environ, clear=True),
                patch.object(
                    env_main, "parse_static_env_with_comments", return_value=({}, {})
                ),
                patch.object(env_main, "build_env") as build_env,
                patch.object(env_main, "write_dotenv") as write_dotenv,
            ):
                build_env.return_value.values = {}
                rc = env_main.main()
            return rc, write_dotenv.called

    def test_a_host_owned_dotenv_is_kept(self) -> None:
        self.assertEqual(self._run(dotenv_exists=True, host_owned="true"), (0, False))

    def test_a_missing_dotenv_is_generated_even_when_host_owned(self) -> None:
        self.assertEqual(self._run(dotenv_exists=False, host_owned="true"), (0, True))

    def test_without_the_marker_the_dotenv_is_regenerated(self) -> None:
        self.assertEqual(self._run(dotenv_exists=True, host_owned=None), (0, True))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
