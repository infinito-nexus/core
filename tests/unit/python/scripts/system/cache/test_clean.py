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
RAW_DOCKER_STUB = '#!/usr/bin/env bash\nprintf "raw-docker %s\\n" "$*" >>"$STUB_LOG"\n'
PYTHON_STUB = """#!/usr/bin/env bash
printf 'python %s\\n' "$*" >>"$STUB_LOG"
case "$3" in
cache-name) echo "inner-$4" ;;
docker) [[ "$4" == ps ]] && printf '%s\\n' inner-registry inner-package {1..10000} ;;
esac
exit 0
"""


def clean(
    exported: tuple[str, ...],
) -> tuple[subprocess.CompletedProcess, set[str], list[str]]:
    """Run clean.sh with an env loader that exports ``exported``.

    Args:
        exported: the cache keys the stub env loader exports, each naming its
            own populated folder.

    Returns:
        The finished process, the keys whose folder still exists and the
        logged docker and python calls.
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
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        stubs = {"docker": RAW_DOCKER_STUB, "sudo": STUB, "python-stub": PYTHON_STUB}
        for name, body in stubs.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        loader.write_text(
            f"export PYTHON={bin_dir / 'python-stub'}\n"
            + "".join(f"export {key}={folders[key]}\n" for key in exported)
        )
        log = Path(tmp) / "calls.log"
        log.touch()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in KEYS and k not in ("BASH_ENV", "PYTHON")
        }
        env.update(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", STUB_LOG=str(log))
        done = subprocess.run(
            ["bash", str(script_dir / "clean.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = log.read_text().splitlines()  # nocheck: cache-read  stub call log
        return done, {key for key, folder in folders.items() if folder.exists()}, calls


class TestCleanCache(unittest.TestCase):
    def test_the_shared_folder_goes_with_the_other_caches(self) -> None:
        done, left, _calls = clean(KEYS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(left, set())

    def test_an_env_without_the_shared_key_still_cleans_the_other_caches(
        self,
    ) -> None:
        done, left, _calls = clean(KEYS[:3])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(left, {SHARED})

    def test_the_caches_stop_inside_the_infra_runner_only(self) -> None:
        _done, _left, calls = clean(KEYS)
        self.assertIn(
            "python -m cli.administration.infra docker stop inner-registry inner-package",
            calls,
        )
        self.assertEqual([c for c in calls if c.startswith("raw-docker")], [])


if __name__ == "__main__":
    unittest.main()
