from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.roles.design.gallery import main
from utils.design.gallery import GALLERY_ROOT


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestGalleryCli(unittest.TestCase):
    def test_path_prints_the_app_gallery(self) -> None:
        self.assertEqual(
            _run(["path", "web-app-gitea"]),
            (0, f"{GALLERY_ROOT / 'web-app-gitea'}\n", ""),
        )

    def test_a_bad_application_id_exits_two_without_output(self) -> None:
        code, out, err = _run(["path", "../web-app-gitea"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no application id", err)

    def test_manifest_prints_shots_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            after = Path(tmp) / "web-app-gitea" / "after"
            after.mkdir(parents=True)
            for name in ("home-light-desktop.png", "home-dark-desktop.png"):
                (after / name).write_bytes(b"\x89PNG")
            (after / "login-light-desktop.png").write_bytes(b"\x89PNG")
            with patch("cli.meta.roles.design.gallery.GALLERY_ROOT", Path(tmp)):
                code, out, _ = _run(["manifest", "web-app-gitea"])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {
                "gallery": f"{tmp}/web-app-gitea",
                "manifest": {
                    "after": {
                        "home": ["dark-desktop", "light-desktop"],
                        "login": ["light-desktop"],
                    }
                },
                "gaps": ["after/login: missing dark-desktop"],
            },
        )


if __name__ == "__main__":
    unittest.main()
