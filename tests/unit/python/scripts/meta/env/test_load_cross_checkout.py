from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

LOADER_DIR = Path(PROJECT_ROOT) / "scripts" / "meta" / "env"
LOADER = Path("scripts") / "meta" / "env" / "load.sh"
STAMP = "2026-11-13 21:48:33"


def clean_env(**overrides: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("INFINITO_")
        and k not in ("BASH_ENV", "ENV_SH", "PYTHONPATH", "VENV", "PYTHON")
    }
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.update(overrides)
    return env


class TestCrossCheckout(unittest.TestCase):
    def checkout(self, instance: int, container: str) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / LOADER).parent.mkdir(parents=True)
        for name in ("load.sh", "python.sh"):
            shutil.copy(LOADER_DIR / name, root / LOADER.parent)
        dotenv = root / ".env"
        dotenv.write_text(
            f"INFINITO_INSTANCE={instance}\nINFINITO_CONTAINER={container}\n",
            encoding="utf-8",
        )
        subprocess.run(["touch", "-d", STAMP, str(dotenv)], check=True)
        return root

    def test_a_second_checkout_loads_its_own_dotenv(self) -> None:
        caller = self.checkout(255, "caller_lane")
        target = self.checkout(226, "target_lane")
        script = (
            f'source "{caller / LOADER}"\nsource "{target / LOADER}"\n'
            'printf "%s" "${INFINITO_CONTAINER}"'
        )

        shown = subprocess.run(
            ["bash", "-c", script],
            env=clean_env(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        self.assertEqual("target_lane", shown)

    def test_a_nested_make_reads_its_own_env_loader(self) -> None:
        caller = self.checkout(255, "caller_lane")

        shown = subprocess.run(
            [
                "make",
                "--no-print-directory",
                "-C",
                str(PROJECT_ROOT),
                "-n",
                "--eval",
                "cross-checkout-probe: ; @: $(info ENV_SH=$(ENV_SH))",
                "cross-checkout-probe",
            ],
            env=clean_env(ENV_SH=str(caller / LOADER)),
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        self.assertIn(f"ENV_SH={Path(PROJECT_ROOT) / LOADER}\n", shown)


if __name__ == "__main__":
    unittest.main()
