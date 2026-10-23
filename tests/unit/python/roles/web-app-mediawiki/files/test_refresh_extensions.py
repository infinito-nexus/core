import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/web-app-mediawiki/files/shell/refresh_extensions.sh"
MARKER = ".infinito-mediawiki-version"


def _volume_file(path: Path) -> str:
    return path.read_text()  # nocheck: cache-read tempdir fixture


class TestRefreshExtensions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.html_dir = root / "html"
        self.volume = root / "volume"
        bundled = self.html_dir / "extensions"
        (bundled / "VisualEditor").mkdir(parents=True)
        (bundled / "VisualEditor" / "extension.json").write_text('{"version": "new"}')
        (bundled / "README").write_text("bundled\n")
        self.volume.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stale_volume(self, recorded: str | None) -> None:
        (self.volume / "VisualEditor").mkdir()
        (self.volume / "VisualEditor" / "extension.json").write_text(
            '{"version": "old"}'
        )
        (self.volume / "OpenIDConnect" / "vendor").mkdir(parents=True)
        (self.volume / "OpenIDConnect" / "extension.json").write_text("{}")
        if recorded is not None:
            (self.volume / MARKER).write_text(f"{recorded}\n")

    def _run(self, version: str | None) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "MEDIAWIKI_VERSION"
        }
        if version is not None:
            env["MEDIAWIKI_VERSION"] = version
        return subprocess.run(
            ["bash", "-s", "--", str(self.html_dir), str(self.volume), MARKER],
            input=read_text(str(SCRIPT)),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_volume_without_marker_is_reseeded_from_the_image(self) -> None:
        self._stale_volume(recorded=None)

        result = self._run("1.46.2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REFRESHED:none->1.46.2", result.stdout)
        self.assertEqual(
            _volume_file(self.volume / "VisualEditor" / "extension.json"),
            '{"version": "new"}',
        )

    def test_reseed_drops_add_ons_so_they_are_reinstalled_for_the_new_branch(
        self,
    ) -> None:
        self._stale_volume(recorded="1.45.1")

        result = self._run("1.46.2")

        self.assertIn("REFRESHED:1.45.1->1.46.2", result.stdout)
        self.assertFalse((self.volume / "OpenIDConnect").exists())

    def test_reseed_records_the_image_version(self) -> None:
        self._stale_volume(recorded="1.45.1")

        self._run("1.46.2")

        self.assertEqual(_volume_file(self.volume / MARKER), "1.46.2\n")

    def test_volume_of_the_running_version_is_left_alone(self) -> None:
        self._stale_volume(recorded="1.46.2")

        result = self._run("1.46.2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CURRENT:1.46.2", result.stdout)
        self.assertTrue((self.volume / "OpenIDConnect" / "extension.json").is_file())
        self.assertEqual(
            _volume_file(self.volume / "VisualEditor" / "extension.json"),
            '{"version": "old"}',
        )

    def test_a_patch_release_counts_as_a_version_change(self) -> None:
        self._stale_volume(recorded="1.46.1")

        result = self._run("1.46.2")

        self.assertIn("REFRESHED:1.46.1->1.46.2", result.stdout)

    def test_unrecorded_volume_seeded_by_the_same_image_is_adopted(self) -> None:
        (self.volume / "VisualEditor").mkdir()
        (self.volume / "VisualEditor" / "extension.json").write_text(
            '{"version": "new"}'
        )
        (self.volume / "OpenIDConnect").mkdir()
        (self.volume / "OpenIDConnect" / "extension.json").write_text("{}")

        result = self._run("1.46.2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ADOPTED:1.46.2", result.stdout)
        self.assertTrue((self.volume / "OpenIDConnect" / "extension.json").is_file())
        self.assertEqual(_volume_file(self.volume / MARKER), "1.46.2\n")

    def test_unrecorded_volume_missing_a_bundled_extension_is_reseeded(self) -> None:
        result = self._run("1.46.2")

        self.assertIn("REFRESHED:none->1.46.2", result.stdout)
        self.assertTrue((self.volume / "VisualEditor" / "extension.json").is_file())

    def test_volume_of_a_newer_version_is_refused_and_kept(self) -> None:
        self._stale_volume(recorded="1.46.10")

        result = self._run("1.46.2")

        self.assertEqual(result.returncode, 3)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("MediaWiki 1.46.10, newer than the image's 1.46.2", result.stdout)
        self.assertTrue((self.volume / "OpenIDConnect" / "extension.json").is_file())

    def test_missing_image_version_fails_without_touching_the_volume(self) -> None:
        self._stale_volume(recorded="1.45.1")

        result = self._run(None)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MEDIAWIKI_VERSION must be set", result.stderr)
        self.assertTrue((self.volume / "OpenIDConnect" / "extension.json").is_file())


if __name__ == "__main__":
    unittest.main()
