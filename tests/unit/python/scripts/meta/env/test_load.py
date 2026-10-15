"""The distro-derived keys follow the distro the caller asks for.

``scripts/tests/deploy/distros.sh`` exports ``INFINITO_DISTRO`` per iteration
and sources the loader again. The keys composed from the distro must then name
that distro, not the one ``.env`` was generated for, and ``.env`` itself must
stay as it was.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import PROJECT_ROOT

LOADER_DIR = Path(PROJECT_ROOT) / "scripts" / "meta" / "env"
SHOWN = (
    "INFINITO_DISTRO",
    "INFINITO_CONTAINER",
    "INFINITO_PARENT_IMAGE",
    "INFINITO_IMAGE",
)
SHOW = "printf '%s\\n' " + " ".join(f'"{key}=${{{key}:-}}"' for key in SHOWN)


def clean_env(**overrides: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("INFINITO_")
        and k not in ("BASH_ENV", "PYTHONPATH", "VENV", "PYTHON", "VIRTUAL_ENV")
    }
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.update(overrides)
    return env


def bash(script: str, cwd: Path) -> dict[str, str]:
    proc = subprocess.run(
        ["bash", "-c", f"{script}\n{SHOW}"],
        env=clean_env(),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in proc.stdout.splitlines())


class TestDistroDerivedKeys(unittest.TestCase):
    scratch: ClassVar[Path]
    expected: ClassVar[dict[str, dict[str, str]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = Path(tempfile.mkdtemp())
        cls.expected = {}
        for distro in ("debian", "centos"):
            path = cls.scratch / f"{distro}.env"
            subprocess.run(
                [sys.executable, "-m", "cli.meta.env", "--output", str(path)],
                env=clean_env(INFINITO_DISTRO=distro),
                cwd=PROJECT_ROOT,
                capture_output=True,
                check=True,
            )
            cls.expected[distro] = bash(f'set -a; source "{path}"', cls.scratch)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.scratch)

    def run_loader(self, steps: str) -> dict[str, str]:
        """Source a copy of the loader in a checkout whose ``.env`` is debian's.

        Args:
            steps: bash run before the keys are shown; ``load`` sources the
                loader.

        Returns:
            The keys as the steps leave them.
        """
        checkout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, checkout)
        (checkout / "scripts" / "meta" / "env").mkdir(parents=True)
        for name in ("load.sh", "python.sh"):
            shutil.copy(LOADER_DIR / name, checkout / "scripts" / "meta" / "env")
        dotenv = checkout / ".env"
        shutil.copy(self.scratch / "debian.env", dotenv)
        shown = bash(
            f"load() {{ source scripts/meta/env/load.sh; }}\n{steps}", checkout
        )
        self.assertTrue(
            filecmp.cmp(dotenv, self.scratch / "debian.env", shallow=False),
            ".env was rewritten",
        )
        return shown

    def test_the_two_distros_derive_different_keys(self):
        self.assertNotEqual(
            self.expected["debian"]["INFINITO_PARENT_IMAGE"],
            self.expected["centos"]["INFINITO_PARENT_IMAGE"],
        )

    def test_a_distro_exported_after_the_first_load_gets_its_own_keys(self):
        shown = self.run_loader("load\nexport INFINITO_DISTRO=centos\nload")
        self.assertEqual(shown, self.expected["centos"])

    def test_a_distro_exported_before_the_first_load_gets_its_own_keys(self):
        shown = self.run_loader("export INFINITO_DISTRO=centos\nload")
        self.assertEqual(shown, self.expected["centos"])

    def test_switching_back_restores_the_keys_of_the_dotenv(self):
        shown = self.run_loader(
            "load\nexport INFINITO_DISTRO=centos\nload\n"
            "export INFINITO_DISTRO=debian\nload"
        )
        self.assertEqual(shown, self.expected["debian"])

    def test_a_caller_value_for_the_loaded_distro_still_wins(self):
        shown = self.run_loader(
            "load\nexport INFINITO_PARENT_IMAGE=caller/image:pinned\n"
            "touch -d '+1 minute' .env\nload"
        )
        self.assertEqual(shown["INFINITO_PARENT_IMAGE"], "caller/image:pinned")


if __name__ == "__main__":
    unittest.main()
