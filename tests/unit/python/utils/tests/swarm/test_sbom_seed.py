from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace

from utils.tests.swarm import sbom_seed

BASE = "http://10.0.0.2:5000"
LAYERS = ("sha256:l1", "sha256:l2")
MANIFEST = {
    "config": {"digest": "sha256:cfg"},
    "layers": [{"size": 10}, {"size": 32}],
}
CONFIG = {"rootfs": {"diff_ids": list(LAYERS)}}


def _registry(pages):
    def fetch(url, _accept):
        if url not in pages:
            raise urllib.error.URLError("no route")
        return pages[url]

    return fetch


def _single_image_pages():
    return {
        f"{BASE}/v2/_catalog?n={sbom_seed.CATALOG_PAGE}": (
            {"repositories": ["mirror/redis"]},
            "",
        ),
        f"{BASE}/v2/mirror/redis/tags/list": ({"tags": ["8"]}, ""),
        f"{BASE}/v2/mirror/redis/manifests/8": (MANIFEST, "sha256:man"),
        f"{BASE}/v2/mirror/redis/blobs/sha256:cfg": (CONFIG, ""),
    }


class TestRegistryEntries(unittest.TestCase):
    def test_a_tag_becomes_one_entry_with_its_layers_and_size(self):
        entries = sbom_seed.registry_entries(
            BASE, "amd64", _registry(_single_image_pages())
        )
        self.assertEqual(
            entries, [sbom_seed.Entry("mirror/redis", "sha256:man", LAYERS, 42)]
        )

    def test_an_index_resolves_to_the_lab_architecture(self):
        pages = _single_image_pages()
        pages[f"{BASE}/v2/mirror/redis/manifests/8"] = (
            {
                "manifests": [
                    {
                        "digest": "sha256:amd",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "digest": "sha256:arm",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ]
            },
            "sha256:index",
        )
        pages[f"{BASE}/v2/mirror/redis/manifests/sha256:arm"] = (MANIFEST, "sha256:arm")
        entries = sbom_seed.registry_entries(BASE, "arm64", _registry(pages))
        self.assertEqual([entry.digest for entry in entries], ["sha256:arm"])

    def test_a_manifest_without_a_digest_is_left_out(self):
        pages = _single_image_pages()
        pages[f"{BASE}/v2/mirror/redis/manifests/8"] = (MANIFEST, "")
        self.assertEqual(
            sbom_seed.registry_entries(BASE, "amd64", _registry(pages)), []
        )

    def test_a_registry_that_does_not_answer_yields_nothing(self):
        self.assertEqual(sbom_seed.registry_entries(BASE, "amd64", _registry({})), [])

    def test_two_tags_of_one_image_yield_one_entry(self):
        pages = _single_image_pages()
        pages[f"{BASE}/v2/mirror/redis/tags/list"] = ({"tags": ["8", "latest"]}, "")
        pages[f"{BASE}/v2/mirror/redis/manifests/latest"] = (MANIFEST, "sha256:man")
        self.assertEqual(
            len(sbom_seed.registry_entries(BASE, "amd64", _registry(pages))), 1
        )


class _SeedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.seed = Path(self.tmp.name)
        self.entry = sbom_seed.Entry("mirror/redis", "sha256:man", LAYERS, 42)

    def tearDown(self):
        self.tmp.cleanup()

    def _syft(self, recorded, returncode):
        def run(work):
            document = {
                "source": {"metadata": {"layers": [{"digest": d} for d in recorded]}}
            }
            (work / sbom_seed.SYFT_OUTPUT).write_text(
                json.dumps(document), encoding="utf-8"
            )
            (work / sbom_seed.CYCLONEDX_OUTPUT).write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=returncode)

        return run


class TestSeedEntry(_SeedCase):
    def test_a_read_of_the_entry_lands_under_its_layer_key(self):
        built = sbom_seed.seed_entry(self.entry, self.seed, self._syft(LAYERS, 0))
        paths = sbom_seed.seed_paths(self.seed, LAYERS)
        self.assertEqual(
            (
                built,
                [path.is_file() for path in paths],
                sorted(p.name for p in self.seed.iterdir()),
            ),
            (True, [True, True], sorted(path.name for path in paths)),
        )

    def test_a_read_that_records_other_layers_is_discarded(self):
        built = sbom_seed.seed_entry(
            self.entry, self.seed, self._syft(("sha256:x",), 0)
        )
        self.assertEqual((built, list(self.seed.iterdir())), (False, []))

    def test_a_failed_read_leaves_nothing_behind(self):
        built = sbom_seed.seed_entry(self.entry, self.seed, self._syft(LAYERS, 1))
        self.assertEqual((built, list(self.seed.iterdir())), (False, []))


class TestSeedPass(_SeedCase):
    def _pass(self, entries, room, stopped):
        calls, lines = [], []
        told = set()
        for _ in range(2):
            sbom_seed.seed_pass(
                entries,
                self.seed,
                lambda entry: (
                    calls.append(entry)
                    or sbom_seed.seed_entry(
                        entry, self.seed, self._syft(entry.layers, 0)
                    )
                ),
                lambda _entry: room,
                lines.append,
                told,
                lambda: stopped,
            )
        return calls, lines

    def test_an_entry_is_read_once_and_then_taken_from_the_seed(self):
        calls, lines = self._pass([self.entry], True, False)
        self.assertEqual((calls, len(lines)), ([self.entry], 1))

    def test_an_entry_without_room_waits_and_says_so_once(self):
        calls, lines = self._pass([self.entry], False, False)
        self.assertEqual((calls, len(lines)), ([], 1))
        self.assertIn("waits", lines[0])

    def test_a_stopped_seeder_reads_nothing(self):
        calls, _lines = self._pass([self.entry], True, True)
        self.assertEqual(calls, [])


class TestSyftCommand(unittest.TestCase):
    def test_the_read_goes_to_the_registry_bounded_and_over_plain_http(self):
        argv = sbom_seed.syft_command(
            sbom_seed.Entry("mirror/redis", "sha256:man", LAYERS, 42),
            "10.0.0.2:5000",
            Path("/seed/.work-1"),
            "ghcr.io/anchore/syft:v1",
            "infinito-sbom-seed-1",
        )
        self.assertEqual(
            (
                "registry:10.0.0.2:5000/mirror/redis@sha256:man" in argv,
                "SYFT_REGISTRY_INSECURE_USE_HTTP=true" in argv,
                argv[argv.index("--memory") + 1],
                argv[argv.index("--network") + 1],
            ),
            (True, True, sbom_seed.MEMORY_LIMIT, "host"),
        )


if __name__ == "__main__":
    unittest.main()
