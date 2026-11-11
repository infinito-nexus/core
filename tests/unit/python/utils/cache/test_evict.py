from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from unittest.mock import patch

from cli.meta.cache.evict import __main__ as evict_cli
from utils import PROJECT_ROOT
from utils.cache import evict
from utils.cache.artefacts import Artefact
from utils.cache.evict import (
    CACHES,
    FLOOR_KEY,
    Cache,
    OutsideCacheError,
    Settings,
    Usage,
    measure,
    plan,
    remove,
)
from utils.cache.eviction.docker import build_cache_usage
from utils.cache.eviction.nexus import Asset, NexusRest, nexus_from_env
from utils.cache.eviction.units import Unit, model_units, shared_units
from utils.cache.files import read_text

DAY = 86400
NOW = time.time()
CHUNK = 64 * 1024
IDLE_DAYS = 30
AMPLE = 10**15
FREE = 10**18


def _file(path: Path, days_ago: float) -> Path:
    """
    Args:
        path: the file to write with CHUNK bytes.
        days_ago: how many days ago it was last accessed and modified.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(CHUNK))
    stamp = NOW - days_ago * DAY
    os.utime(path, (stamp, stamp))
    return path


def _size(*paths: Path) -> int:
    return sum(
        measure(path).used if path.is_dir() else os.lstat(path).st_blocks * 512
        for path in paths
    )


def _settings(root: Path, shared_cap: int, models_cap: int, floor: int) -> Settings:
    """
    Args:
        root: the temporary cache base.
        shared_cap: the cap over all shared folders.
        models_cap: the cap of the models folder.
        floor: the disk floor.
    """
    caps = {"shared": shared_cap, "models": models_cap}
    caches = tuple(
        Cache(
            name=spec.name,
            path=root / spec.name if spec.path_key else None,
            cap_key=spec.cap_key,
            cap=caps.get(spec.name, 0),
        )
        for spec in CACHES
    )
    return Settings(caches=caches, idle_seconds=IDLE_DAYS * DAY, floor=floor)


def _measured(settings: Settings) -> dict[str, Usage]:
    return evict.usages(settings, Usage(used=0, complete=True))


def _run(
    settings: Settings,
    free: int,
    tools: bool | None,
    nexus: object,
    declared: frozenset[str] | None = frozenset(),
) -> tuple[int, str]:
    """Args:
        settings: the caches under test.
        free: the free bytes the floor check sees.
        tools: what the tools probe answers for the models folder.
        nexus: the Nexus store the eviction opens, None when it does not answer.
        declared: the artefact digests a role still declares, None when unknown.

    Returns:
        The exit code and the report.
    """
    out = io.StringIO()
    code = evict.evict(
        settings,
        _measured(settings),
        free,
        NOW,
        lambda _models: tools,
        lambda: nexus,
        out,
        lambda: declared,
    )
    return code, out.getvalue()


def _npm_bucket(
    cacache: Path, key: str, content: Path | None, days_ago: float
) -> tuple[Path, Path]:
    """Args:
        cacache: the npm `_cacache` directory.
        key: the cache key the bucket indexes.
        content: an existing content file to reference, None to write a new one.
        days_ago: the access age of the bucket and of a newly written content file.

    Returns:
        The bucket file and the content file it references.
    """
    if content is None:
        payload = os.urandom(CHUNK)
        digest = hashlib.sha512(payload).digest()
        hexdigest = digest.hex()
        content = (
            cacache
            / "content-v2"
            / "sha512"
            / hexdigest[:2]
            / hexdigest[2:4]
            / hexdigest[4:]
        )
        content.parent.mkdir(parents=True, exist_ok=True)
        content.write_bytes(payload)
        stamp = NOW - days_ago * DAY
        os.utime(content, (stamp, stamp))
    hexdigest = "".join(content.relative_to(cacache / "content-v2" / "sha512").parts)
    integrity = "sha512-" + base64.b64encode(bytes.fromhex(hexdigest)).decode()
    entry = json.dumps({"key": key, "integrity": integrity, "time": 0, "size": CHUNK})
    bucket_hash = hashlib.sha256(key.encode()).hexdigest()
    bucket = cacache / "index-v5" / bucket_hash[:2] / bucket_hash[2:4] / bucket_hash[4:]
    bucket.parent.mkdir(parents=True, exist_ok=True)
    bucket.write_text(f"{hashlib.sha1(entry.encode()).hexdigest()}\t{entry}\n")  # noqa: S324 - fixture mimics the sha1 line checksum of npm cacache index buckets, no security use
    stamp = NOW - days_ago * DAY
    os.utime(bucket, (stamp, stamp))
    return bucket, content


class TestSharedFolders(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.shared = self.root / "shared"
        self.shared.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_age_eviction_runs_before_size_eviction(self) -> None:
        stale = _file(self.shared / "pip" / "wheels" / "stale.whl", 40)
        older = _file(self.shared / "pip" / "wheels" / "older.whl", 5)
        newer = _file(self.shared / "pip" / "wheels" / "newer.whl", 1)
        cap = measure(self.shared).used - _size(stale, older)
        code, _ = _run(_settings(self.root, cap, AMPLE, 0), FREE, False, None)
        self.assertEqual(code, 0)
        self.assertEqual(
            [stale.exists(), older.exists(), newer.exists()], [False, False, True]
        )
        self.assertLessEqual(measure(self.shared).used, cap)

    def test_an_idle_entry_goes_even_below_the_cap(self) -> None:
        stale = _file(self.shared / "pip" / "wheels" / "stale.whl", 31)
        fresh = _file(self.shared / "pip" / "wheels" / "fresh.whl", 29)
        _run(_settings(self.root, AMPLE, AMPLE, 0), FREE, False, None)
        self.assertEqual([stale.exists(), fresh.exists()], [False, True])

    def test_one_cap_covers_every_shared_folder_together(self) -> None:
        pip_old = _file(self.shared / "pip" / "wheels" / "a.whl", 9)
        pacman_old = _file(self.shared / "pacman" / "a.pkg.tar.zst", 8)
        pip_new = _file(self.shared / "pip" / "wheels" / "b.whl", 2)
        pacman_new = _file(self.shared / "pacman" / "b.pkg.tar.zst", 1)
        cap = measure(self.shared).used - _size(pip_old, pacman_old)
        _run(_settings(self.root, cap, AMPLE, 0), FREE, False, None)
        self.assertEqual(
            [
                pip_old.exists(),
                pacman_old.exists(),
                pip_new.exists(),
                pacman_new.exists(),
            ],
            [False, False, True, True],
        )
        self.assertLessEqual(measure(self.shared).used, cap)

    def test_a_sidecar_goes_with_its_entry(self) -> None:
        package = _file(self.shared / "pacman" / "a.pkg.tar.zst", 1)
        signature = _file(self.shared / "pacman" / "a.pkg.tar.zst.sig", 40)
        body = _file(self.shared / "pip" / "http-v2" / "a" / "b" / "c.body", 40)
        meta = _file(self.shared / "pip" / "http-v2" / "a" / "b" / "c", 40)
        _run(_settings(self.root, AMPLE, AMPLE, 0), FREE, False, None)
        self.assertEqual(
            [package.exists(), signature.exists(), body.exists(), meta.exists()],
            [True, True, False, False],
        )

    def test_npm_content_goes_only_with_its_index_entry(self) -> None:
        cacache = self.shared / "npm" / "_cacache"
        stale_bucket, stale_content = _npm_bucket(cacache, "stale", None, 40)
        shared_bucket, shared_content = _npm_bucket(cacache, "old-alias", None, 40)
        fresh_bucket, _ = _npm_bucket(cacache, "fresh-alias", shared_content, 1)
        orphan = _file(cacache / "content-v2" / "sha512" / "ff" / "ee" / "orphan", 40)
        _run(_settings(self.root, AMPLE, AMPLE, 0), FREE, False, None)
        self.assertEqual(
            [
                stale_bucket.exists(),
                stale_content.exists(),
                shared_bucket.exists(),
                shared_content.exists(),
                fresh_bucket.exists(),
                orphan.exists(),
            ],
            [False, False, True, True, True, False],
        )

    def test_reading_an_index_keeps_its_access_time(self) -> None:
        bucket, _ = _npm_bucket(self.shared / "npm" / "_cacache", "kept", None, 20)
        before = os.lstat(bucket).st_atime_ns
        shared_units(self.shared, False)
        self.assertEqual(os.lstat(bucket).st_atime_ns, before)

    def test_a_playwright_browser_is_one_unit_and_its_links_stay(self) -> None:
        browser = self.shared / "ms-playwright" / "chromium-1000"
        _file(browser / "chrome-linux" / "chrome", 40)
        _file(browser / "INSTALLATION_COMPLETE", 1)
        stale_browser = self.shared / "ms-playwright" / "firefox-900"
        _file(stale_browser / "firefox" / "firefox", 40)
        link = _file(self.shared / "ms-playwright" / ".links" / "abc", 40)
        _run(_settings(self.root, AMPLE, AMPLE, 0), FREE, False, None)
        self.assertEqual(
            [
                (browser / "chrome-linux" / "chrome").exists(),
                stale_browser.exists(),
                link.exists(),
            ],
            [True, False, True],
        )

    def test_the_first_eviction_migrates_without_recreating_the_cache(self) -> None:
        inode = os.lstat(self.shared).st_ino
        files = [
            _file(self.shared / "pip" / "wheels" / f"{age}.whl", age)
            for age in (6, 5, 4, 3, 2, 1)
        ]
        link = _file(self.shared / "ms-playwright" / ".links" / "abc", 2)
        cap = measure(self.shared).used - _size(*files[:3])
        _run(_settings(self.root, cap, AMPLE, 0), FREE, False, None)
        self.assertLessEqual(measure(self.shared).used, cap)
        self.assertEqual(
            [path.exists() for path in files], [False, False, False, True, True, True]
        )
        self.assertEqual(os.lstat(self.shared).st_ino, inode)
        self.assertTrue((self.shared / "pip" / "wheels").is_dir())
        self.assertTrue(link.exists())

    def test_noatime_falls_back_to_the_modification_time(self) -> None:
        path = _file(self.shared / "pip" / "wheels" / "a.whl", 40)
        os.utime(path, (NOW, NOW - 40 * DAY))
        self.assertEqual(
            plan(shared_units(self.shared, False), 0, AMPLE, NOW, IDLE_DAYS * DAY), []
        )
        self.assertEqual(
            [
                unit.paths
                for unit in plan(
                    shared_units(self.shared, True), 0, AMPLE, NOW, IDLE_DAYS * DAY
                )
            ],
            [(path,)],
        )

    def test_status_names_the_noatime_fallback(self) -> None:
        settings = _settings(self.root, AMPLE, AMPLE, 0)
        with patch(
            "utils.cache.evict.os.statvfs",
            return_value=SimpleNamespace(f_flag=os.ST_NOATIME),
        ):
            rows = {
                row["name"]: row for row in evict.status(settings, _measured(settings))
            }
        self.assertTrue(rows["shared"]["atime_fallback"])
        with patch(
            "utils.cache.evict.os.statvfs", return_value=SimpleNamespace(f_flag=0)
        ):
            rows = {
                row["name"]: row for row in evict.status(settings, _measured(settings))
            }
        self.assertFalse(rows["shared"]["atime_fallback"])

    def test_nothing_outside_the_cache_is_removed(self) -> None:
        outside = _file(self.root / "elsewhere" / "keep.bin", 40)
        link = self.shared / "pip" / "link.bin"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        os.utime(link, (NOW - 40 * DAY, NOW - 40 * DAY), follow_symlinks=False)
        _run(_settings(self.root, 0, 0, 0), FREE, False, None)
        self.assertTrue(outside.exists())
        self.assertFalse(link.is_symlink())
        with self.assertRaises(OutsideCacheError):
            remove(Unit(paths=(outside,), size=1, used_at=0), self.shared)
        with self.assertRaises(OutsideCacheError):
            remove(Unit(paths=(self.shared,), size=1, used_at=0), self.shared)
        for p in ("pip/..", ".."):  # nocheck: project-root-import  deliberate traversal
            parent = self.shared / p
            with self.subTest(path=parent), self.assertRaises(OutsideCacheError):
                remove(Unit(paths=(parent,), size=1, used_at=0), self.shared)
        self.assertTrue(outside.exists())
        self.assertTrue(self.shared.is_dir())
        self.assertTrue((self.shared / "pip").is_dir())


class TestModels(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.models = self.root / "models"
        self.models.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_model_package_goes_whole_or_not_at_all(self) -> None:
        used = self.models / "libretranslate" / "translate-en_de-1_9"
        _file(used / "model" / "model.bin", 40)
        _file(used / "metadata.json", 2)
        idle = self.models / "libretranslate" / "translate-en_fr-1_9"
        _file(idle / "model" / "model.bin", 40)
        _file(idle / "metadata.json", 40)
        code, _ = _run(_settings(self.root, AMPLE, AMPLE, 0), FREE, False, None)
        self.assertEqual(code, 0)
        self.assertEqual(
            [
                (used / "model" / "model.bin").exists(),
                idle.exists(),
                (self.models / "libretranslate").is_dir(),
            ],
            [True, False, True],
        )

    def test_the_least_recently_used_model_goes_first_above_the_cap(self) -> None:
        old = self.models / "libretranslate" / "old"
        _file(old / "model.bin", 3)
        new = self.models / "libretranslate" / "new"
        _file(new / "model.bin", 1)
        cap = measure(self.models).used - _size(old)
        _run(_settings(self.root, AMPLE, cap, 0), FREE, False, None)
        self.assertEqual([old.exists(), new.exists()], [False, True])
        self.assertLessEqual(measure(self.models).used, cap)

    def test_an_ollama_model_keeps_the_blobs_another_model_uses(self) -> None:
        ollama = self.models / "ollama"
        common = _file(ollama / "blobs" / "sha256-common", 40)
        own = _file(ollama / "blobs" / "sha256-own", 40)
        alone = _file(ollama / "blobs" / "sha256-alone", 40)
        manifests = ollama / "manifests" / "registry.ollama.ai" / "library"
        for name, digests, days in (
            ("idle", ["sha256:common", "sha256:own"], 40),
            ("used", ["sha256:common"], 1),
            ("gone", ["sha256:alone"], 40),
        ):
            manifest = manifests / name / "latest"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                json.dumps(
                    {
                        "config": {"digest": digests[0]},
                        "layers": [{"digest": d} for d in digests],
                    }
                )
            )
            os.utime(manifest, (NOW - days * DAY, NOW - days * DAY))
        units = model_units(self.models, False)
        self.assertTrue(all(len(unit.paths) >= 2 for unit in units))
        _run(_settings(self.root, AMPLE, AMPLE, 0), FREE, False, None)
        self.assertEqual(
            [common.exists(), own.exists(), (manifests / "used" / "latest").exists()],
            [True, True, True],
        )
        self.assertEqual(
            [alone.exists(), (manifests / "gone" / "latest").exists()], [False, False]
        )

    def test_no_model_goes_while_a_tools_service_may_run(self) -> None:
        idle = self.models / "libretranslate" / "idle"
        _file(idle / "model.bin", 40)
        for answer in (True, None):
            code, report = _run(_settings(self.root, AMPLE, 0, 0), FREE, answer, None)
            self.assertEqual(code, 0)
            self.assertTrue(idle.exists())
            self.assertIn("skipped", report)


class TestDeclaredArtefacts(unittest.TestCase):
    DIGEST = "a" * 64
    STALE = "b" * 64

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.models = self.root / "models"
        self.models.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_declared_artefact_stays_however_idle_and_above_the_cap(self) -> None:
        kept = _file(self.models / self.DIGEST, 400)
        stale = _file(self.models / self.STALE, 400)
        model = _file(self.models / "libretranslate" / "idle" / "model.bin", 400)
        code, _ = _run(
            _settings(self.root, AMPLE, 0, 0),
            FREE,
            False,
            None,
            frozenset({self.DIGEST}),
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            [kept.exists(), stale.exists(), model.exists()], [True, False, False]
        )

    def test_only_a_store_entry_named_by_the_digest_is_kept(self) -> None:
        nested = _file(self.models / "libretranslate" / self.DIGEST, 400)
        _run(
            _settings(self.root, AMPLE, 0, 0),
            FREE,
            False,
            None,
            frozenset({self.DIGEST}),
        )
        self.assertFalse(nested.exists())

    def test_unknown_declarations_skip_the_models_and_say_so(self) -> None:
        stored = _file(self.models / self.DIGEST, 400)
        code, report = _run(_settings(self.root, AMPLE, 0, 0), FREE, False, None, None)
        self.assertEqual(code, 0)
        self.assertTrue(stored.exists())
        self.assertIn("skipped, the declared artefacts are unknown", report)

    def test_the_cli_keeps_what_the_checkout_and_the_pin_declare(self) -> None:
        own = Artefact("own", "https://h/f", "c" * 40, self.DIGEST, "1", "role")
        with patch.object(evict_cli, "artefacts", return_value=[own]):
            for pinned, expected in (
                (frozenset({self.STALE}), frozenset({self.DIGEST, self.STALE})),
                (frozenset(), frozenset({self.DIGEST})),
                (None, None),
            ):
                with (
                    self.subTest(pinned=pinned),
                    patch.object(evict_cli.pin, "pinned_digests", return_value=pinned),
                ):
                    self.assertEqual(evict_cli.declared_digests(), expected)


class TestDiskFloor(unittest.TestCase):
    def test_a_floor_violation_refuses_before_evicting_and_names_every_cap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = _file(root / "shared" / "pip" / "stale.whl", 40)
            settings = _settings(root, 10 * 2**30, 30 * 2**30, 15 * 2**30)
            code, report = _run(settings, 2**30, False, None)
            self.assertEqual(code, 1)
            self.assertTrue(stale.exists())
            for spec in CACHES:
                self.assertIn(spec.cap_key, report)
            self.assertIn(FLOOR_KEY, report)

    def test_the_eviction_passes_when_the_caps_leave_the_floor_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = _file(root / "shared" / "pip" / "stale.whl", 40)
            settings = _settings(root, 10 * 2**30, 30 * 2**30, 15 * 2**30)
            code, report = _run(settings, 56 * 2**30, False, None)
            self.assertEqual(code, 0, report)
            self.assertFalse(stale.exists())

    def test_the_floor_counts_free_plus_used_minus_the_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(Path(tmp), 10, 20, 15)
            measured = {spec.name: Usage(used=0, complete=True) for spec in CACHES}
            measured["shared"] = Usage(used=5, complete=True)
            self.assertEqual(evict.floor_violation(settings, measured, 40), [])
            self.assertNotEqual(evict.floor_violation(settings, measured, 39), [])


ALL_TASKS = frozenset(
    {evict.CLEANUP_TASK, evict.ASSET_BLOB_CLEANUP_TASK, evict.COMPACT_TASK}
)


class FakeNexus:
    def __init__(self, assets: list[Asset], overhead: int, tasks: frozenset) -> None:
        """
        Args:
            assets: the assets the blob store holds.
            overhead: bytes the blob store holds beside its assets.
            tasks: the task types Nexus has scheduled.
        """
        self.live = {asset.id: asset for asset in assets}
        self.unused = 0
        self.soft_deleted = 0
        self.overhead = overhead
        self.tasks = tasks
        self.deleted: list[str] = []
        self.runs: list[str] = []

    def used(self) -> int:
        return (
            self.overhead
            + self.unused
            + self.soft_deleted
            + sum(asset.size for asset in self.live.values())
        )

    def assets(self) -> list[Asset]:
        return list(self.live.values())

    def delete(self, asset_id: str) -> None:
        self.unused += self.live.pop(asset_id).size
        self.deleted.append(asset_id)

    def run(self, task_type: str) -> None:
        if task_type not in self.tasks:
            raise LookupError(f"Nexus has no {task_type} task")
        self.runs.append(task_type)
        if task_type == evict.ASSET_BLOB_CLEANUP_TASK:
            self.soft_deleted += self.unused
            self.unused = 0
        if task_type == evict.COMPACT_TASK:
            self.soft_deleted = 0


NEXUS_TASK_ORDER = (
    evict.CLEANUP_TASK,
    evict.ASSET_BLOB_CLEANUP_TASK,
    evict.COMPACT_TASK,
)


class _Body:
    def __init__(self, payload: object) -> None:
        self.payload = b"" if payload is None else json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class NexusHttp:
    def __init__(self, assets: dict[str, tuple[int, int]]) -> None:
        """
        Args:
            assets: size in bytes and day of the last download of every asset of the one proxy.
        """
        self.assets = dict(assets)
        self.unused = 0
        self.soft_deleted = 0
        self.last_run: dict[str, int] = {}
        self.deleted: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def urlopen(self, request: object, timeout: float) -> _Body:
        url = urllib.parse.urlsplit(request.full_url)
        method = request.get_method()
        path = url.path.removeprefix("/service/rest")
        query = dict(urllib.parse.parse_qsl(url.query))
        self.calls.append((method, path))
        return _Body(self._answer(method, path, query))

    def _answer(self, method: str, path: str, query: dict[str, str]) -> object:
        parts = path.split("/")
        if (method, path) == ("GET", "/v1/blobstores"):
            size = sum(size for size, _ in self.assets.values())
            used = size + self.unused + self.soft_deleted
            return [{"name": "default", "totalSizeInBytes": used}]
        if (method, path) == ("GET", "/v1/repositories"):
            return [{"name": "pypi", "type": "proxy"}, {"name": "all", "type": "group"}]
        if (method, path) == ("GET", "/v1/assets") and query == {"repository": "pypi"}:
            items = [
                {
                    "id": asset_id,
                    "fileSize": size,
                    "lastDownloaded": f"2026-01-0{day}T00:00:00.000+00:00",
                    "blobCreated": "2025-12-01T00:00:00.000+00:00",
                }
                for asset_id, (size, day) in self.assets.items()
            ]
            return {"items": items, "continuationToken": None}
        if method == "DELETE" and parts[:3] == ["", "v1", "assets"] and len(parts) == 4:
            self.unused += self.assets.pop(parts[3])[0]
            self.deleted.append(parts[3])
            return None
        if (method, path) == ("GET", "/v1/tasks") and query.keys() == {"type"}:
            task = query["type"]
            items = [{"id": task, "lastRun": self.last_run.get(task)}]
            return {"items": items, "continuationToken": None}
        if (
            method == "POST"
            and parts[:3] == ["", "v1", "tasks"]
            and parts[4:] == ["run"]
        ):
            self._complete(parts[3])
            return None
        if method == "GET" and parts[:3] == ["", "v1", "tasks"] and len(parts) == 4:
            task = parts[3]
            return {
                "id": task,
                "currentState": "WAITING",
                "lastRun": self.last_run[task],
            }
        raise AssertionError(f"Nexus 3.91.1 has no route {method} {path} {query}")

    def _complete(self, task: str) -> None:
        self.last_run[task] = self.last_run.get(task, 0) + 1
        if task == evict.ASSET_BLOB_CLEANUP_TASK:
            self.soft_deleted += self.unused
            self.unused = 0
        if task == evict.COMPACT_TASK:
            self.soft_deleted = 0


class TestNexusEviction(unittest.TestCase):
    def test_the_least_recently_downloaded_assets_go_until_the_compacted_store_fits(
        self,
    ) -> None:
        assets = [
            Asset(id=f"a{age}", size=100, used_at=NOW - age * DAY)
            for age in (1, 9, 3, 7, 5)
        ]
        store = FakeNexus(assets, 50, ALL_TASKS)
        before, after = evict.evict_package(store, 300)
        self.assertEqual(before, 550)
        self.assertLessEqual(after, 300)
        self.assertEqual(store.deleted, ["a9", "a7", "a5"])
        cycle = [evict.ASSET_BLOB_CLEANUP_TASK, evict.COMPACT_TASK]
        self.assertEqual(store.runs[:3], [evict.CLEANUP_TASK, *cycle])
        self.assertEqual(store.runs[-2:], cycle)

    def test_a_store_under_its_cap_after_the_age_cleanup_loses_nothing(self) -> None:
        store = FakeNexus([Asset(id="a", size=100, used_at=NOW)], 0, ALL_TASKS)
        self.assertEqual(evict.evict_package(store, 300), (100, 100))
        self.assertEqual(store.deleted, [])

    def test_the_eviction_reports_the_package_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FakeNexus([Asset(id="a", size=100, used_at=NOW)], 0, ALL_TASKS)
            code, report = _run(
                _settings(Path(tmp), AMPLE, AMPLE, 0), FREE, False, store
            )
            self.assertEqual(code, 0)
            self.assertIn("package: blob store 100 -> 0 bytes, cap 0", report)
            self.assertEqual(store.deleted, ["a"])

    def test_a_store_without_its_compaction_task_fails_the_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FakeNexus(
                [Asset(id="a", size=100, used_at=NOW)],
                0,
                ALL_TASKS - {evict.COMPACT_TASK},
            )
            code, report = _run(
                _settings(Path(tmp), AMPLE, AMPLE, 0), FREE, False, store
            )
            self.assertEqual(code, 1)
            self.assertIn(f"package: Nexus has no {evict.COMPACT_TASK} task", report)

    def test_the_rest_client_uses_only_the_routes_of_the_pinned_nexus(self) -> None:
        nexus = NexusHttp({"old": (100, 1), "mid": (100, 2), "new": (100, 3)})
        client = NexusRest("http://nexus/service/rest", "admin", "pw", 0, 5)
        with patch("urllib.request.urlopen", nexus.urlopen):
            before, after = evict.evict_package(client, 150)
        self.assertEqual((before, after), (300, 100))
        self.assertEqual(nexus.deleted, ["old", "mid"])
        self.assertEqual(
            [path for method, path in nexus.calls if method == "POST"][:3],
            [f"/v1/tasks/{task}/run" for task in NEXUS_TASK_ORDER],
        )

    def test_the_client_needs_a_host_a_port_and_a_password(self) -> None:
        env = {
            "INFINITO_CACHE_PACKAGE_REST_HOST": " 127.0.0.1 ",
            "INFINITO_CACHE_PACKAGE_PORT": " 8081 ",
            "INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD": " pw ",
        }
        with patch.object(NexusRest, "reachable", return_value=True):
            client = nexus_from_env(env, 0, 5)
            self.assertEqual(client.base, "http://127.0.0.1:8081/service/rest")
            self.assertEqual(client.headers, NexusRest("", "admin", "pw", 0, 5).headers)
            for key in env:
                for value in (None, "", "  "):
                    lacking = {k: v for k, v in env.items() if k != key}
                    if value is not None:
                        lacking[key] = value
                    with self.subTest(key=key, value=value):
                        self.assertIsNone(nexus_from_env(lacking, 0, 5))
        with patch.object(NexusRest, "reachable", return_value=False):
            self.assertIsNone(nexus_from_env(env, 0, 5))

    def test_a_store_left_above_its_cap_fails_the_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FakeNexus([], 100, ALL_TASKS)
            code, report = _run(
                _settings(Path(tmp), AMPLE, AMPLE, 0), FREE, False, store
            )
            self.assertEqual(code, 1)
            self.assertIn("package: blob store 100 -> 100 bytes, cap 0", report)


DOCKER_DOWN = "#!/usr/bin/env bash\nexit 1\n"


class TestStatus(unittest.TestCase):
    def test_status_prints_one_object_per_cache_without_any_running_stack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "docker").write_text(DOCKER_DOWN)
            (bin_dir / "docker").chmod(0o755)
            _file(root / "shared" / "pip" / "a.whl", 1)
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
                    "PYTHONPATH": str(PROJECT_ROOT),
                    "INFINITO_CACHE_REGISTRY_HOST_PATH": str(root / "registry"),
                    "INFINITO_CACHE_PACKAGE_HOST_PATH": str(root / "package"),
                    "INFINITO_CACHE_SHARED_HOST_PATH": str(root / "shared"),
                    "INFINITO_TOOLS_MODELS_HOST_PATH": str(root / "models"),
                    "INFINITO_CACHE_REGISTRY_MAX_SIZE": "40g",
                    "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX": "20g",
                    "INFINITO_CACHE_SHARED_MAX_SIZE": "10g",
                    "INFINITO_TOOLS_MODELS_MAX_SIZE": "30g",
                    "INFINITO_BUILD_CACHE_MAX_SIZE": "20g",
                    "INFINITO_CACHE_MAX_IDLE_DAYS": "30",
                    "INFINITO_CACHE_DISK_FLOOR": "15g",
                }
            )
            done = subprocess.run(
                [sys.executable, "-m", "cli.meta.cache.status"],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([row["name"] for row in rows], [spec.name for spec in CACHES])
        for row in rows:
            self.assertEqual(
                set(row),
                {
                    "name",
                    "path",
                    "used_bytes",
                    "cap_bytes",
                    "headroom_bytes",
                    "cap_variable",
                    "atime_fallback",
                    "complete",
                },
            )
        shared = rows[[spec.name for spec in CACHES].index("shared")]
        self.assertEqual(shared["cap_bytes"], 10 * 2**30)
        self.assertEqual(
            shared["headroom_bytes"], shared["cap_bytes"] - shared["used_bytes"]
        )
        self.assertGreater(shared["used_bytes"], 0)
        build = rows[-1]
        self.assertEqual(
            [build["path"], build["used_bytes"], build["complete"]], [None, None, False]
        )
        pin_rows = [
            json.loads(line)
            for line in done.stderr.splitlines()
            if line.startswith("{")
        ]
        self.assertEqual([row["cache"] for row in pin_rows], ["pin"])

    def test_the_build_cache_size_comes_from_docker_system_df(self) -> None:
        line = json.dumps({"Type": "Build Cache", "Size": "28.5GB"})
        usage = build_cache_usage(
            lambda _command: f'{{"Type":"Images","Size":"1GB"}}\n{line}\n'
        )
        self.assertEqual(usage, Usage(used=28_500_000_000, complete=True))

    def test_the_make_targets_run_the_cache_cli(self) -> None:
        makefile = read_text(str(PROJECT_ROOT / "Makefile"))
        self.assertIn(
            'cache-evict:\n\t@"$${PYTHON}" -m cli.meta.cache.evict\n', makefile
        )
        self.assertIn(
            'cache-status:\n\t@"$${PYTHON}" -m cli.meta.cache.status\n', makefile
        )


if __name__ == "__main__":
    unittest.main()
