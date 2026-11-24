"""The model prefetch runs inside the LibreTranslate image, whose argostranslate
and libretranslate packages are absent here, so both are stubbed before the
module is executed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
import unittest.mock
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "svc-ai-libretranslate-engine"
    / "files"
    / "python"
    / "prefetch_models.py"
)


class FakePackage:
    def __init__(self, from_code: str, to_code: str, path: Path | None = None) -> None:
        self.from_code = from_code
        self.to_code = to_code
        self._path = path

    def download(self) -> Path:
        return self._path


def _load() -> types.ModuleType:
    package = types.ModuleType("argostranslate.package")
    package.update_package_index = lambda: None
    package.get_available_packages = list
    settings = types.ModuleType("argostranslate.settings")
    settings.package_data_dir = Path(os.devnull)
    argos = types.ModuleType("argostranslate")
    argos.package = package
    argos.settings = settings

    language = types.ModuleType("libretranslate.language")
    language.iso2model = list
    libretranslate = types.ModuleType("libretranslate")
    libretranslate.language = language

    minisbd = types.ModuleType("minisbd")
    minisbd.download_models = lambda *args: None

    modules = {
        "argostranslate": argos,
        "argostranslate.package": package,
        "argostranslate.settings": settings,
        "libretranslate": libretranslate,
        "libretranslate.language": language,
        "minisbd": minisbd,
    }
    with unittest.mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("prefetch_models", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
    return module


class TestWanted(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()
        self.available = [
            FakePackage("en", "de"),
            FakePackage("de", "en"),
            FakePackage("en", "fr"),
            FakePackage("fr", "ru"),
        ]
        self.module.package.get_available_packages = lambda: self.available

    def _pairs(self, codes: list[str], directions: str) -> list[tuple[str, str]]:
        kept, _ = self.module.wanted(codes, directions)
        return [(p.from_code, p.to_code) for p in kept]

    def test_no_codes_keeps_every_package(self) -> None:
        kept, model_codes = self.module.wanted([], "both")

        self.assertEqual(kept, self.available)
        self.assertEqual(model_codes, [])

    def test_a_pair_survives_only_when_both_sides_are_wanted(self) -> None:
        self.assertEqual(
            self._pairs(["en", "de"], "both"), [("en", "de"), ("de", "en")]
        )

    def test_from_source_drops_the_return_direction(self) -> None:
        self.assertEqual(self._pairs([], "from_source"), [("en", "de"), ("en", "fr")])

    def test_from_source_composes_with_a_code_filter(self) -> None:
        self.assertEqual(self._pairs(["en", "de"], "from_source"), [("en", "de")])

    def test_a_code_no_package_offers_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.module.wanted(["en", "xx"], "both")

        self.assertIn("xx", str(caught.exception))

    def test_an_empty_selection_is_refused(self) -> None:
        self.available = [FakePackage("de", "en")]
        self.module.package.get_available_packages = lambda: self.available

        with self.assertRaises(ValueError):
            self.module.wanted([], "from_source")


class TestMain(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        archive = self.root / "en_zh.argosmodel"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("metadata.json", "{}")

        self.module.package.get_available_packages = lambda: [
            FakePackage("en", "zh-Hans", archive)
        ]
        self.module.package.install_from_path = lambda path: None
        self.module.libretranslate.language.iso2model = lambda codes: [
            "zh-Hans" if code == "zh" else code for code in codes
        ]
        self.minisbd_got: list = []
        self.module.download_models = lambda codes, _: self.minisbd_got.append(codes)

    def test_minisbd_gets_the_model_codes_not_the_iso_codes(self) -> None:
        with unittest.mock.patch.object(
            sys, "argv", ["prefetch_models.py", "--load_only_lang_codes", "en,zh"]
        ):
            self.assertEqual(self.module.main(), 0)

        self.assertEqual(self.minisbd_got, [["en", "zh-Hans"]])

    def test_minisbd_gets_none_when_no_codes_were_requested(self) -> None:
        with unittest.mock.patch.object(sys, "argv", ["prefetch_models.py"]):
            self.assertEqual(self.module.main(), 0)

        self.assertEqual(self.minisbd_got, [None])

    def _unpacking(self) -> list[tuple[str, bool]]:
        unpacked: list[tuple[str, bool]] = []
        self.module.package.install_from_path = lambda path: unpacked.append(
            (Path(path).name, zipfile.is_zipfile(path))
        )
        return unpacked

    def test_an_archive_is_unpacked_whole_then_leaves_no_copy_in_the_layer(
        self,
    ) -> None:
        archive = self.root / "en_zh.argosmodel"
        unpacked = self._unpacking()

        with unittest.mock.patch.object(sys, "argv", ["prefetch_models.py"]):
            self.assertEqual(self.module.main(), 0)

        self.assertEqual(unpacked, [(archive.name, True)])
        self.assertFalse(archive.exists())

    def test_a_retry_unpacks_what_the_failed_run_fetched_then_removes_it(
        self,
    ) -> None:
        archive = self.root / "en_zh.argosmodel"
        broken = self.root / "en_de.argosmodel"
        broken.write_bytes(b"half a download")
        unpacked = self._unpacking()
        self.module.package.get_available_packages = lambda: [
            FakePackage("en", "zh-Hans", archive),
            FakePackage("en", "de", broken),
        ]

        with (
            unittest.mock.patch.object(sys, "argv", ["prefetch_models.py"]),
            self.assertRaises(RuntimeError),
        ):
            self.module.main()
        fetched_before_the_retry = zipfile.is_zipfile(archive)
        with zipfile.ZipFile(broken, "w") as handle:
            handle.writestr("metadata.json", "{}")
        with unittest.mock.patch.object(sys, "argv", ["prefetch_models.py"]):
            self.assertEqual(self.module.main(), 0)

        self.assertTrue(fetched_before_the_retry)
        self.assertEqual(unpacked, [(archive.name, True), (broken.name, True)])
        self.assertEqual(sorted(self.root.iterdir()), [])


class TestFetch(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _archive(self, name: str, *, valid: bool) -> Path:
        path = self.root / name
        if valid:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("metadata.json", "{}")
        else:
            path.write_bytes(b"half a download")
        return path

    def test_a_complete_archive_is_kept(self) -> None:
        path = self._archive("good.argosmodel", valid=True)

        self.assertEqual(self.module.fetch(FakePackage("en", "de", path)), path)
        self.assertTrue(path.exists())

    def test_a_truncated_archive_is_dropped_so_the_cache_refetches_it(self) -> None:
        path = self._archive("bad.argosmodel", valid=False)

        with self.assertRaises(RuntimeError):
            self.module.fetch(FakePackage("en", "de", path))

        self.assertFalse(path.exists())


class TestInstall(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.packages = self.root / "packages"
        self.packages.mkdir()
        self.module.settings.package_data_dir = self.packages

    def _archive(self, *names: str) -> Path:
        path = self.root / "model.argosmodel"
        with zipfile.ZipFile(path, "w") as archive:
            for name in names:
                archive.writestr(name, "x")
        return path

    def _extract_all(self, path: Path) -> None:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(self.packages)

    def _interrupted_after_first_member(self, path: Path) -> None:
        with zipfile.ZipFile(path) as archive:
            archive.extract(archive.namelist()[0], self.packages)
        raise EOFError

    def test_a_failed_install_leaves_no_partial_package(self) -> None:
        path = self._archive(
            "translate-de_en-1_3/model/model.bin", "translate-de_en-1_3/metadata.json"
        )
        self.module.package.install_from_path = self._interrupted_after_first_member

        with self.assertRaises(EOFError):
            self.module.install(path)

        self.assertEqual(list(self.packages.iterdir()), [])

    def test_a_completed_install_is_kept(self) -> None:
        path = self._archive("translate-de_en-1_3/metadata.json")
        self.module.package.install_from_path = self._extract_all

        self.module.install(path)

        self.assertTrue(
            (self.packages / "translate-de_en-1_3" / "metadata.json").exists()
        )

    def test_cleanup_stays_inside_the_package_directory(self) -> None:
        sibling = self.root / "sibling"
        sibling.mkdir()
        path = self._archive(
            f"{os.pardir}/sibling/x", "/sibling/x", "translate-de_en-1_3/metadata.json"
        )
        self.module.package.install_from_path = self._interrupted_after_first_member

        with self.assertRaises(EOFError):
            self.module.install(path)

        self.assertTrue(sibling.exists())


if __name__ == "__main__":
    unittest.main()
