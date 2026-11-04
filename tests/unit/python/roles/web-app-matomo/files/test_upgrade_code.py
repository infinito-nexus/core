import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/web-app-matomo/files/shell/upgrade_code.sh"
OWNER = f"{os.getuid()}:{os.getgid()}"


def _version_php(release: str) -> str:
    return (
        "<?php\n\nnamespace Piwik;\n\nfinal class Version\n{\n"
        f"    public const VERSION = '{release}';\n\n"
        "    public const MAJOR_VERSION = 5;\n}\n"
    )


def _content(path: Path) -> str:
    return path.read_text()  # nocheck: cache-read tempdir fixture the script rewrites


class TestUpgradeCode(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.release = root / "release"
        self.volume = root / "volume"
        self.release.mkdir()
        self.volume.mkdir()

    def _write(self, tree: Path, files: dict[str, str]) -> None:
        for name, content in files.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def _ship(self, release: str, files: dict[str, str]) -> None:
        self._write(self.release, {"core/Version.php": _version_php(release), **files})

    def _install(self, release: str, files: dict[str, str]) -> None:
        self._write(self.volume, {"core/Version.php": _version_php(release), **files})

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", "-s", "--", str(self.release), str(self.volume), OWNER],
            input=read_text(str(SCRIPT)),
            capture_output=True,
            text=True,
            check=False,
        )

    def _upgrade(self) -> subprocess.CompletedProcess[str]:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_a_volume_on_the_shipped_release_is_left_alone(self) -> None:
        self._ship("5.14.0", {"core/Shipped.php": "new"})
        self._install("5.14.0", {"core/Local.php": "kept"})

        result = self._upgrade()

        self.assertEqual(result.stdout, "current 5.14.0\n")
        self.assertTrue((self.volume / "core/Local.php").is_file())
        self.assertFalse((self.volume / "core/Shipped.php").exists())

    def test_an_older_volume_gets_the_shipped_release(self) -> None:
        self._ship("5.14.0", {"core/Shipped.php": "new"})
        self._install("5.3.2", {})

        result = self._upgrade()

        self.assertEqual(result.stdout, "upgraded 5.3.2 5.14.0\n")
        self.assertIn("'5.14.0'", _content(self.volume / "core/Version.php"))
        self.assertEqual(_content(self.volume / "core/Shipped.php"), "new")

    def test_a_second_run_after_the_upgrade_changes_nothing(self) -> None:
        self._ship("5.14.0", {})
        self._install("5.3.2", {})
        self._upgrade()

        self.assertEqual(self._upgrade().stdout, "current 5.14.0\n")

    def test_the_upgrade_keeps_the_site_configuration_and_user_files(self) -> None:
        self._ship(
            "5.14.0",
            {
                "config/global.ini.php": "release defaults",
                "misc/user/index.html": "release",
                "plugins/CoreHome/plugin.json": "{}",
            },
        )
        self._install(
            "5.3.2",
            {
                "config/global.ini.php": "old defaults",
                "config/config.ini.php": "[database]\nhost = db\n",
                "misc/user/logo.svg": "<svg/>",
                "plugins/MarketplacePlugin/plugin.json": "{}",
            },
        )

        self._upgrade()

        self.assertEqual(
            _content(self.volume / "config/config.ini.php"), "[database]\nhost = db\n"
        )
        self.assertEqual(
            _content(self.volume / "config/global.ini.php"), "release defaults"
        )
        self.assertEqual(_content(self.volume / "misc/user/logo.svg"), "<svg/>")
        self.assertTrue(
            (self.volume / "plugins/MarketplacePlugin/plugin.json").is_file()
        )

    def test_the_upgrade_removes_what_the_release_dropped_from_its_own_trees(
        self,
    ) -> None:
        self._ship(
            "5.14.0",
            {
                "core/Kept.php": "new",
                "vendor/autoload.php": "new",
                "plugins/CoreHome/plugin.json": "{}",
            },
        )
        dropped = [
            "core/Dropped.php",
            "libs/Dropped/Lib.php",
            "vendor/dropped/package/Lib.php",
            "node_modules/dropped/index.js",
            "plugins/CoreHome/templates/dropped.twig",
        ]
        self._install("5.3.2", dict.fromkeys(dropped, "old"))

        self._upgrade()

        for name in dropped:
            with self.subTest(name=name):
                self.assertFalse((self.volume / name).exists())
        self.assertFalse((self.volume / "vendor/dropped").exists())
        self.assertTrue((self.volume / "plugins/CoreHome/plugin.json").is_file())

    def test_a_volume_newer_than_the_image_is_refused(self) -> None:
        self._ship("5.3.2", {"core/Shipped.php": "old"})
        self._install("5.14.0", {})

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr)
        self.assertIn("'5.14.0'", _content(self.volume / "core/Version.php"))
        self.assertFalse((self.volume / "core/Shipped.php").exists())

    def test_a_volume_without_a_release_fails(self) -> None:
        self._ship("5.14.0", {})

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.volume / "core/Version.php").exists())


if __name__ == "__main__":
    unittest.main()
