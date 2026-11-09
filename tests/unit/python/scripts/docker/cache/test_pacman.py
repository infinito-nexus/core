from __future__ import annotations

import shlex
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
HOOK = Path("pacman.d") / "hooks" / "infinito-shared-cache.hook"


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

    def _hook(self) -> str:
        hook = self.tmp / HOOK
        return hook.read_text()  # nocheck: cache-read  the script writes it

    def _options(self) -> list[str]:
        lines = self._text().splitlines()
        return lines[: lines.index("") if "" in lines else len(lines)]

    def _stage(self, conf: Path) -> Path:
        prefix = f"CacheDir = {self.shared}/pacman/node-"
        text = conf.read_text()  # nocheck: cache-read  the script rewrites it
        lines = text.splitlines()
        stages = [line for line in lines if line.startswith(prefix)]
        self.assertEqual(len(stages), 1, lines)
        self.assertTrue(stages[0].endswith("/"), stages[0])
        return Path(stages[0].removeprefix("CacheDir = ").rstrip("/"))

    def test_host_cache_comes_first_then_the_node_download_dir_then_the_shared_cache(
        self,
    ) -> None:
        done = layer(self.conf, self.shared, str(self.host))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            self._options()[:4],
            [
                "[options]",
                f"CacheDir = {self.host}/",
                f"CacheDir = {self._stage(self.conf)}/",
                f"CacheDir = {self.shared}/pacman/",
            ],
        )

    def test_every_other_cache_dir_is_dropped_and_the_rest_kept(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        text = self._text()
        self.assertNotIn("CacheDir = /var/cache/pacman/pkg/", text)
        self.assertIn("#CacheDir    = /var/cache/pacman/pkg/", text)
        self.assertIn("[core]\nInclude = /etc/pacman.d/mirrorlist\n", text)

    def test_the_shared_pacman_dir_and_a_traversable_node_download_dir_are_created(
        self,
    ) -> None:
        layer(self.conf, self.shared, str(self.host))
        stage = self._stage(self.conf)
        self.assertTrue((self.shared / "pacman").is_dir())
        self.assertTrue(stage.is_dir())
        self.assertEqual(stage.parent, self.shared / "pacman")
        self.assertEqual(stage.stat().st_mode & 0o777, 0o755)

    def test_a_second_run_changes_nothing(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        first, first_hook = self._text(), self._hook()
        done = layer(self.conf, self.shared, str(self.host))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self._text(), first)
        self.assertEqual(self._hook(), first_hook)
        self.assertEqual(len(list((self.shared / "pacman").glob("node-*"))), 1)

    def test_a_second_run_recreates_a_removed_node_download_dir_under_its_name(
        self,
    ) -> None:
        layer(self.conf, self.shared, str(self.host))
        stage = self._stage(self.conf)
        stage.rmdir()
        first = self._text()
        layer(self.conf, self.shared, str(self.host))
        self.assertEqual(self._text(), first)
        self.assertTrue(stage.is_dir())

    def test_two_nodes_on_one_shared_folder_download_into_different_dirs(self) -> None:
        other = self.tmp / "other" / "pacman.conf"
        other.parent.mkdir()
        other.write_text(CONF)
        layer(self.conf, self.shared, str(self.host))
        layer(other, self.shared, str(self.host))
        self.assertNotEqual(self._stage(self.conf), self._stage(other))
        self.assertTrue(self._stage(other).is_dir())

    def test_an_empty_host_cache_leaves_the_node_download_dir_and_the_shared_layer(
        self,
    ) -> None:
        layer(self.conf, self.shared, "")
        self.assertEqual(
            self._options()[:3],
            [
                "[options]",
                f"CacheDir = {self._stage(self.conf)}/",
                f"CacheDir = {self.shared}/pacman/",
            ],
        )
        self.assertEqual(
            sum(line.startswith("CacheDir") for line in self._options()), 2
        )

    def test_the_hook_runs_after_every_install_and_upgrade(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        hook = self._hook().splitlines()
        for line in (
            "Operation = Install",
            "Operation = Upgrade",
            "Type = Package",
            "Target = *",
            "When = PostTransaction",
        ):
            self.assertIn(line, hook)

    def test_the_hook_publishes_finished_downloads_and_keeps_partials(self) -> None:
        layer(self.conf, self.shared, str(self.host))
        stage = self._stage(self.conf)
        own = self.shared / "pacman"
        for name in ("a-1-1-any.pkg.tar.zst", "a-1-1-any.pkg.tar.zst.sig"):
            (stage / name).write_text(name)
        (stage / "b-1-1-any.pkg.tar.zst.part").write_text("partial")
        (own / "a-1-1-any.pkg.tar.zst").write_text("stale")
        (exec_line,) = [
            line for line in self._hook().splitlines() if line.startswith("Exec = ")
        ]
        done = subprocess.run(
            shlex.split(exec_line.removeprefix("Exec = ")),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            sorted(path.name for path in stage.iterdir()),
            ["b-1-1-any.pkg.tar.zst.part"],
        )
        published = own / "a-1-1-any.pkg.tar.zst"
        self.assertEqual(
            published.read_text(),  # nocheck: cache-read  the hook moves it
            "a-1-1-any.pkg.tar.zst",
        )
        self.assertTrue((own / "a-1-1-any.pkg.tar.zst.sig").is_file())

    def test_a_system_without_pacman_conf_is_left_alone(self) -> None:
        done = layer(self.tmp / "absent.conf", self.shared, str(self.host))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.shared.exists())
        self.assertFalse((self.tmp / HOOK).exists())

    def test_a_host_cache_that_is_not_mounted_fails(self) -> None:
        done = layer(self.conf, self.shared, str(self.tmp / "missing"))
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self._text(), CONF)
        self.assertFalse((self.tmp / HOOK).exists())

    def test_a_hook_dir_override_fails(self) -> None:
        conf = CONF.replace("[options]\n", "[options]\nHookDir = /srv/hooks/\n")
        self.conf.write_text(conf)
        done = layer(self.conf, self.shared, str(self.host))
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self._text(), conf)
        self.assertFalse(self.shared.exists())

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
