"""clean.sh removes the shared cache folder together with the other cache state."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

CLEAN = PROJECT_ROOT / "scripts" / "system" / "cache" / "clean.sh"
SHARED = "INFINITO_CACHE_SHARED_HOST_PATH"
KEYS = (
    "INFINITO_CACHE_REGISTRY_HOST_PATH",
    "INFINITO_CACHE_REGISTRY_CA_HOST_PATH",
    "INFINITO_CACHE_PACKAGE_HOST_PATH",
    SHARED,
)
STUB = "#!/usr/bin/env bash\nexit 0\n"


def clean(exported: tuple[str, ...]) -> tuple[subprocess.CompletedProcess, set[str]]:
    """Run clean.sh with an env loader that exports ``exported``.

    Args:
        exported: the cache keys the stub env loader exports, each naming its
            own populated folder.

    Returns:
        The finished process and the keys whose folder still exists.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        script_dir = root / "scripts" / "system" / "cache"
        script_dir.mkdir(parents=True)
        (script_dir / "clean.sh").symlink_to(CLEAN)
        loader = root / "scripts" / "meta" / "env" / "load.sh"
        loader.parent.mkdir(parents=True)
        folders = {key: Path(tmp) / "state" / key.lower() for key in KEYS}
        for folder in folders.values():
            folder.mkdir(parents=True)
            (folder / "blob").write_text("cached")
        loader.write_text("".join(f"export {key}={folders[key]}\n" for key in exported))
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for name in ("docker", "sudo"):
            (bin_dir / name).write_text(STUB)
            (bin_dir / name).chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k not in KEYS and k != "BASH_ENV"}
        env.update(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        done = subprocess.run(
            ["bash", str(script_dir / "clean.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, {key for key, folder in folders.items() if folder.exists()}


class TestCleanCache(unittest.TestCase):
    def test_the_shared_folder_goes_with_the_other_caches(self) -> None:
        done, left = clean(KEYS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(left, set())

    def test_an_env_without_the_shared_key_still_cleans_the_other_caches(
        self,
    ) -> None:
        done, left = clean(KEYS[:3])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(left, {SHARED})


if __name__ == "__main__":
    unittest.main()
