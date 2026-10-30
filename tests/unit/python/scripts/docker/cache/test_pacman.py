"""pacman.sh layers the read-only host cache first and the shared cache second."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "docker" / "cache" / "pacman.sh"
CONF = """\
[options]
#CacheDir    = /var/cache/pacman/pkg/
CacheDir = /var/cache/pacman/pkg/
HoldPkg     = pacman glibc
Architecture = auto

[core]
Include = /etc/pacman.d/mirrorlist
"""


def layer(conf: Path, shared: Path, host: str) -> subprocess.CompletedProcess:
    """Run pacman.sh against ``conf``.

    Args:
        conf: the pacman.conf to rewrite.
        shared: the shared cache root.
        host: the read-only host cache, empty for none.
    """
    return subprocess.run(
        ["bash", str(SCRIPT), str(conf), str(shared), host],
        capture_output=True,
        text=True,
        check=False,
    )


class TestPacmanCacheLayering(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.conf = self.tmp / "pacman.conf"
        self.conf.write_text(CONF)
        self.shared = self.tmp / "shared"
        self.host = self.tmp / "host-pkg"
        self.host.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _text(self) -> str:
        return self.conf.read_text()  # nocheck: cache-read  the script rewrites it

    def _options(self) -> list[str]:
        lines = self._text().splitlines()
        return lines[: lines.index("") if "" in lines else len(lines)]

    def test_host_cache_comes_first_and_shared_cache_second(self) -> None:
        done = layer(self.conf, self.shared, str(self.host))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            self._options()[:3],
            [
                "[options]",
                f"CacheDir = {self.host}/",
                f"CacheDir = {self.shared}/pacman/",
            ],
        )

    def test_every_other_cache_dir_is_dropped_and_the_rest_kept(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        text = self._text()
        self.assertNotIn("CacheDir = /var/cache/pacman/pkg/", text)
        self.assertIn("#CacheDir    = /var/cache/pacman/pkg/", text)
        self.assertIn("[core]\nInclude = /etc/pacman.d/mirrorlist\n", text)

    def test_the_shared_pacman_dir_is_created(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        self.assertTrue((self.shared / "pacman").is_dir())

    def test_a_second_run_changes_nothing(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        first = self._text()
        layer(self.conf, self.shared, str(self.host))
        self.assertEqual(self._text(), first)

    def test_an_empty_host_cache_leaves_only_the_shared_layer(self) -> None:
        layer(self.conf, self.shared, "")
        self.assertEqual(
            self._options()[:2], ["[options]", f"CacheDir = {self.shared}/pacman/"]
        )
        self.assertEqual(
            sum(line.startswith("CacheDir") for line in self._options()), 1
        )

    def test_a_system_without_pacman_conf_is_left_alone(self) -> None:
        done = layer(self.tmp / "absent.conf", self.shared, str(self.host))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.shared.exists())

    def test_a_host_cache_that_is_not_mounted_fails(self) -> None:
        done = layer(self.conf, self.shared, str(self.tmp / "missing"))
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self._text(), CONF)

    def test_a_missing_shared_root_fails(self) -> None:
        done = subprocess.run(
            ["bash", str(SCRIPT), str(self.conf)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
