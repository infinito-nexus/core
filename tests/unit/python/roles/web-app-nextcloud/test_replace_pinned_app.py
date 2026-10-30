from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles/web-app-nextcloud/files/shell/utils/replace_pinned_app.sh"
)
APP = "onlyoffice"
INFO = "appinfo/info.xml"


def _archive(files: dict[str, str]) -> bytes:
    """Return a gzipped tar that holds each file under ``<root>/``.

    Args:
      files: archive member path mapped to its text content.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def _release(version: str, *extra: str) -> dict[str, str]:
    files = {
        f"{APP}/{INFO}": f"<version>{version}</version>",
        f"{APP}/lib/Migration/Version{version}.php": version,
    }
    files.update({f"{APP}/{name}": version for name in extra})
    return files


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text()  # nocheck: cache-read
        for path in sorted(root.rglob("*"))  # nocheck: project-walk
        if path.is_file()
    }


class TestReplacePinnedApp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self._tmp.name) / "custom_apps"
        self.apps.mkdir()
        self.live = self.apps / APP

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, files: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sh", str(SCRIPT), str(self.apps), APP],
            input=_archive(files),
            capture_output=True,
            check=False,
        )

    def _install(self, files: dict[str, str]) -> None:
        self.assertEqual(self._run(files).returncode, 0)

    def _expected(self, files: dict[str, str]) -> dict[str, str]:
        return {name.removeprefix(f"{APP}/"): text for name, text in files.items()}

    def test_a_fresh_install_places_the_release(self):
        release = _release("100201")
        result = self._run(release)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_tree(self.live), self._expected(release))

    def test_a_fresh_install_reports_a_change(self):
        self.assertIn(b"[CHANGED]", self._run(_release("100201")).stdout)

    def test_an_identical_tree_reports_no_change(self):
        release = _release("100201")
        self._install(release)
        result = self._run(release)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(b"[CHANGED]", result.stdout)

    def test_files_of_an_earlier_release_are_removed(self):
        self._install(_release("091501", "js/old.chunk.mjs"))
        release = _release("100201", "js/new.chunk.mjs")
        result = self._run(release)
        self.assertIn(b"[CHANGED]", result.stdout)
        self.assertEqual(_tree(self.live), self._expected(release))

    def test_an_overlaid_tree_with_leftovers_is_healed(self):
        release = _release("100201")
        self._install(release)
        (self.live / "js").mkdir()
        (self.live / "js/leftover.chunk.mjs").write_text("091501")
        result = self._run(release)
        self.assertIn(b"[CHANGED]", result.stdout)
        self.assertEqual(_tree(self.live), self._expected(release))

    def test_a_changed_file_is_replaced(self):
        release = _release("100201")
        self._install(release)
        (self.live / INFO).write_text("<version>patched</version>")
        self.assertIn(b"[CHANGED]", self._run(release).stdout)
        self.assertEqual(_tree(self.live), self._expected(release))

    def test_an_archive_without_the_app_fails(self):
        result = self._run({"other/appinfo/info.xml": "x"})
        self.assertNotEqual(result.returncode, 0)

    def test_an_archive_without_the_app_keeps_the_installed_app(self):
        release = _release("100201")
        self._install(release)
        self._run({"other/appinfo/info.xml": "x"})
        self.assertEqual(_tree(self.live), self._expected(release))

    def test_a_corrupt_archive_keeps_the_installed_app(self):
        release = _release("100201")
        self._install(release)
        result = subprocess.run(
            ["sh", str(SCRIPT), str(self.apps), APP],
            input=b"not a tarball",
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(_tree(self.live), self._expected(release))

    def test_leftovers_of_an_interrupted_run_are_cleared(self):
        (self.apps / f".{APP}.stage/{APP}").mkdir(parents=True)
        (self.apps / f".{APP}.old/js").mkdir(parents=True)
        self._install(_release("100201"))
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()), [APP])

    def test_the_apps_directory_holds_only_the_app_after_a_replace(self):
        self._install(_release("091501"))
        self._install(_release("100201"))
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()), [APP])


if __name__ == "__main__":
    unittest.main()
