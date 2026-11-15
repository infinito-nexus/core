from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

MODULE_PATH = PROJECT_ROOT / "roles" / "svc-ai-models" / "library" / "artefact_store.py"
BODY = b"pinned model weights"
SHA256 = hashlib.sha256(BODY).hexdigest()
URL = "http://cache.test/huggingface.co/org/repo/resolve/0123/model.gguf"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "svc_ai_models_artefact_store", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_module()


def _record(name: str, sha256: str = SHA256, size: int = len(BODY)) -> dict:
    return {"name": name, "url": URL, "sha256": sha256, "bytes": size}


class _FakeFetch:
    def __init__(self, body: bytes = BODY, error: OSError | None = None) -> None:
        self.body = body
        self.error = error
        self.urls: list[str] = []

    def __call__(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        dest.write_bytes(self.body)


class TestArtefactStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_fetches_each_digest_once_into_its_sha256_path(self) -> None:
        fetch = _FakeFetch()
        outcome = _MOD.store(self.root, [_record("a"), _record("b")], fetch)
        stored = (self.root / SHA256).read_bytes()  # nocheck: cache-read tempdir
        self.assertEqual(
            [fetch.urls, outcome["fetched"], stored], [[URL], ["a", "b"], BODY]
        )

    def test_the_stored_file_is_read_only(self) -> None:
        _MOD.store(self.root, [_record("a")], _FakeFetch())
        mode = stat.S_IMODE((self.root / SHA256).stat().st_mode)
        self.assertEqual(mode & 0o222, 0)

    def test_a_second_run_downloads_nothing(self) -> None:
        fetch = _FakeFetch()
        _MOD.store(self.root, [_record("a")], fetch)
        outcome = _MOD.store(self.root, [_record("a")], fetch)
        self.assertEqual(
            [len(fetch.urls), outcome],
            [1, {"fetched": [], "held": ["a"], "linked": [], "unpacked": []}],
        )

    def test_a_digest_mismatch_fails_naming_the_artefact(self) -> None:
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* hashes to"):
            _MOD.store(self.root, [_record("a")], _FakeFetch(body=b"x" * len(BODY)))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_size_mismatch_fails_naming_the_artefact(self) -> None:
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* bytes"):
            _MOD.store(self.root, [_record("a")], _FakeFetch(body=BODY + b"!"))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_failed_fetch_fails_naming_the_artefact(self) -> None:
        fetch = _FakeFetch(error=OSError("connection refused"))
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: fetching"):
            _MOD.store(self.root, [_record("a")], fetch)

    def test_a_corrupt_held_file_is_fetched_again(self) -> None:
        (self.root / SHA256).write_bytes(b"y" * len(BODY))
        outcome = _MOD.store(self.root, [_record("a")], _FakeFetch())
        stored = (self.root / SHA256).read_bytes()  # nocheck: cache-read tempdir
        self.assertEqual([outcome["fetched"], stored], [["a"], BODY])

    def test_a_consumer_check_fails_naming_a_missing_artefact(self) -> None:
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* is missing"):
            _MOD.store(self.root, [_record("a")], None)

    def test_a_consumer_check_passes_on_a_seeded_store(self) -> None:
        _MOD.store(self.root, [_record("a")], _FakeFetch())
        outcome = _MOD.store(self.root, [_record("a")], None)
        self.assertEqual(
            outcome, {"fetched": [], "held": ["a"], "linked": [], "unpacked": []}
        )

    def test_seeding_links_each_file_under_its_upstream_tree_path(self) -> None:
        tree = "tree/huggingface.co/org/repo/resolve/0123/config.json"
        outcome = _MOD.store(self.root, [_record("a") | {"tree": tree}], _FakeFetch())
        link = self.root / tree
        body = link.read_bytes()  # nocheck: cache-read tempdir
        self.assertEqual(
            [outcome["linked"], link.readlink(), body],
            [["a"], self.root / SHA256, BODY],
        )

    def test_a_second_seeding_links_nothing(self) -> None:
        tree = "tree/huggingface.co/org/repo/resolve/0123/config.json"
        _MOD.store(self.root, [_record("a") | {"tree": tree}], _FakeFetch())
        outcome = _MOD.store(self.root, [_record("a") | {"tree": tree}], _FakeFetch())
        self.assertEqual(outcome["linked"], [])

    def test_a_consumer_check_fails_naming_an_unlinked_artefact(self) -> None:
        _MOD.store(self.root, [_record("a")], _FakeFetch())
        tree = "tree/huggingface.co/org/repo/resolve/0123/config.json"
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* does not link"):
            _MOD.store(self.root, [_record("a") | {"tree": tree}], None)


def _package(weights: bytes = b"w" * 64) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("translate-en_de-1_9/metadata.json", '{"from_code": "en"}')
        archive.writestr("translate-en_de-1_9/model/model.bin", weights)
    return buffer.getvalue()


def _argos(body: bytes) -> dict:
    sha256 = hashlib.sha256(body).hexdigest()
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        listed = sum(info.file_size for info in archive.infolist())
    return _record("argos", sha256, len(body)) | {
        "unpack": f"argos-packages/{sha256}",
        "unpacked_bytes": listed,
    }


class TestUnpack(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.addCleanup(self._writable)

    def _writable(self) -> None:
        for parent, _, _ in os.walk(self.root):  # nocheck: project-walk tempdir store
            Path(parent).chmod(0o755)

    def _seed(self, body: bytes) -> dict:
        return _MOD.store(self.root, [_argos(body)], _FakeFetch(body))

    def test_seeding_unpacks_the_package_once_read_only_under_its_digest(
        self,
    ) -> None:
        body = _package()
        outcome = self._seed(body)
        dest = self.root / _argos(body)["unpack"]
        modes = {
            stat.S_IMODE(path.stat().st_mode) & 0o222
            for path in [dest, *dest.rglob("*")]  # nocheck: project-walk tempdir store
        }
        self.assertEqual(
            [outcome["unpacked"], (dest / "metadata.json").is_file(), modes],
            [["argos"], True, {0}],
        )

    def test_a_second_seeding_unpacks_nothing(self) -> None:
        body = _package()
        self._seed(body)
        self.assertEqual(self._seed(body)["unpacked"], [])

    def test_a_new_package_version_unpacks_beside_the_old_one(self) -> None:
        old, new = _package(), _package(b"v" * 64)
        self._seed(old)
        self._seed(new)
        self.assertEqual(
            sorted(p.name for p in (self.root / "argos-packages").iterdir()),
            sorted(hashlib.sha256(body).hexdigest() for body in (old, new)),
        )

    def test_a_package_listing_other_than_its_unpacked_bytes_is_refused(
        self,
    ) -> None:
        body = _package(b"\0" * 100_000)
        for drift in (1, -1):
            with self.subTest(drift=drift):
                record = _argos(body)
                record["unpacked_bytes"] += drift
                with self.assertRaisesRegex(
                    _MOD.ArtefactError, "artefact argos: .* not the declared"
                ):
                    _MOD.store(self.root, [record], _FakeFetch(body))
                self.assertFalse((self.root / record["unpack"]).exists())

    def test_a_consumer_check_fails_naming_a_package_not_unpacked(self) -> None:
        body = _package()
        _MOD.store(self.root, [_argos(body) | {"unpack": ""}], _FakeFetch(body))
        with self.assertRaisesRegex(
            _MOD.ArtefactError, "artefact argos: .* no unpacked package"
        ):
            _MOD.store(self.root, [_argos(body)], None)

    def test_a_consumer_check_passes_on_an_unpacked_package(self) -> None:
        body = _package()
        self._seed(body)
        self.assertEqual(_MOD.store(self.root, [_argos(body)], None)["held"], ["argos"])

    def test_only_a_full_verify_catches_an_unpacked_package_that_grew(self) -> None:
        body = _package()
        self._seed(body)
        metadata = self.root / _argos(body)["unpack"] / "metadata.json"
        metadata.chmod(0o644)
        metadata.write_text('{"from_code": "en", "x": 1}', encoding="utf-8")
        _MOD.store(self.root, [_argos(body)], None)
        with self.assertRaisesRegex(
            _MOD.ArtefactError, "artefact argos: .* not the declared unpacked_bytes"
        ):
            _MOD.store(self.root, [_argos(body)], None, full=True)


def _rewrite(path: Path, body: bytes) -> None:
    path.chmod(0o644)
    path.write_bytes(body)
    path.chmod(0o444)


class TestVerify(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _MOD.store(self.root, [_record("a")], _FakeFetch())
        self.held = self.root / SHA256

    def test_a_held_entry_passes_seed_and_check_without_hashing(self) -> None:
        with patch.object(_MOD, "_sha256", wraps=_MOD._sha256) as hashed:
            seeded = _MOD.store(self.root, [_record("a")], _FakeFetch())
            checked = _MOD.store(self.root, [_record("a")], None)
        self.assertEqual(
            [hashed.call_count, seeded["held"], checked["held"]], [0, ["a"], ["a"]]
        )

    def test_a_held_entry_of_another_size_is_refused_without_hashing(self) -> None:
        _rewrite(self.held, BODY + b"!")
        with (
            patch.object(_MOD, "_sha256", wraps=_MOD._sha256) as hashed,
            self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* bytes"),
        ):
            _MOD.store(self.root, [_record("a")], None)
        self.assertEqual(hashed.call_count, 0)

    def test_a_writable_entry_is_no_verified_entry(self) -> None:
        self.held.chmod(0o644)
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* writable"):
            _MOD.store(self.root, [_record("a")], None)

    def test_only_a_full_verify_catches_a_flipped_byte(self) -> None:
        _rewrite(self.held, b"Q" + BODY[1:])
        self.assertEqual(_MOD.store(self.root, [_record("a")], None)["held"], ["a"])
        with self.assertRaisesRegex(_MOD.ArtefactError, "artefact a: .* hashes to"):
            _MOD.store(self.root, [_record("a")], None, full=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
