from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.update.runner import bump_text, bump_workflows, newest_ubuntu_label

_BADGE = "<br>![Endpoint Badge](https://img.shields.io/endpoint?url=x)"
_PREVIEW = "[![preview](https://img.shields.io/badge/preview-0969DA)](https://x)"
_README = "\n".join(
    [
        "| Image | Architecture | YAML Label | Included Software |",
        "| --------------------|--------------|---------------------|------------------|",
        f"| Ubuntu 28.04 {_PREVIEW}{_BADGE} | x64 | `ubuntu-28.04` | [ubuntu-28.04] |",
        f"| Ubuntu 26.04{_BADGE} | x64 | `ubuntu-26.04` | [ubuntu-26.04] |",
        f"| Ubuntu 26.04 Arm64{_BADGE} | arm64 | `ubuntu-26.04-arm` | [x] |",
        f"| Ubuntu 24.04{_BADGE} | x64 | `ubuntu-latest` or `ubuntu-24.04` | [x] |",
        f"| Ubuntu Slim{_BADGE} | x64 | `ubuntu-slim` | [ubuntu-slim] |",
        f"| macOS 26 Arm64{_BADGE} | arm64 | `macos-26` | [macOS-26-arm64] |",
    ]
)


class TestNewestUbuntuLabel(unittest.TestCase):
    def test_picks_newest_ga_x64_label(self) -> None:
        self.assertEqual("ubuntu-26.04", newest_ubuntu_label(_README))

    def test_none_without_an_ubuntu_row(self) -> None:
        self.assertIsNone(newest_ubuntu_label("| Image | x |\n| macOS | arm64 |"))


class TestBumpText(unittest.TestCase):
    def test_raises_older_and_keeps_newer(self) -> None:
        text = (
            "jobs:\n"
            "  a:\n    runs-on: ubuntu-22.04\n"
            "  b:\n    runs-on: ubuntu-24.04\n"
            "  c:\n    runs-on: ubuntu-28.04\n"
            "  d:\n    runs-on: ubuntu-24.04-arm\n"
            "# runs on ubuntu-24.04 elsewhere\n"
        )
        self.assertEqual(
            "jobs:\n"
            "  a:\n    runs-on: ubuntu-26.04\n"
            "  b:\n    runs-on: ubuntu-26.04\n"
            "  c:\n    runs-on: ubuntu-28.04\n"
            "  d:\n    runs-on: ubuntu-24.04-arm\n"
            "# runs on ubuntu-24.04 elsewhere\n",
            bump_text(text, "ubuntu-26.04"),
        )


class TestBumpWorkflows(unittest.TestCase):
    def test_rewrites_only_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old.yml").write_text("runs-on: ubuntu-24.04\n", encoding="utf-8")
            (root / "new.yml").write_text("runs-on: ubuntu-26.04\n", encoding="utf-8")

            changed = bump_workflows(root, "ubuntu-26.04")

            self.assertEqual([root / "old.yml"], changed)
            self.assertEqual(
                "runs-on: ubuntu-26.04\n", read_text(str(root / "old.yml"))
            )


if __name__ == "__main__":
    unittest.main()
