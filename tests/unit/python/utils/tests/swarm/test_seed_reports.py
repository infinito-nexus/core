from __future__ import annotations

import itertools
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.security.pipeline import pipeline
from utils.tests.swarm import seed_reports
from utils.tests.swarm.sbom_seed import Entry

LAYERS = ("sha256:l1", "sha256:l2")
SYFT = {
    "artifacts": [
        {"id": "a1", "name": "php-cli", "version": "8.4.26", "type": "binary"}
    ],
    "source": {"metadata": {"layers": [{"digest": digest} for digest in LAYERS]}},
}
CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "serialNumber": "urn:uuid:one-run",
    "components": [
        {
            "type": "library",
            "name": "lodash",
            "version": "4.17.15",
            "purl": "pkg:npm/lodash@4.17.15",
        }
    ],
}
IMAGES = {"osv": "osv:1", "grype": "grype:1"}
ENGINE_LAYERS = {"osv:1": ["sha256:osv-1"], "grype:1": ["sha256:grype-1"]}


def _fingerprint(path: Path) -> str:
    text = path.read_text()  # nocheck: cache-read - the seeder just wrote it
    return json.loads(text)["fingerprint"]


class FakeDocker:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(ENGINE_LAYERS[argv[-1]]), stderr=""
            )
        work = next(
            mount.split(":")[0]
            for flag, mount in itertools.pairwise(argv)
            if flag == "-v" and mount.endswith(":/work")
        )
        for flag, value in itertools.pairwise(argv):
            if flag == "--output-file":
                sources = [
                    arg for prev, arg in itertools.pairwise(argv) if prev == "-L"
                ]
                results = [
                    {"source": {"path": source}, "packages": []} for source in sources
                ]
                Path(work, Path(value).name).write_text(
                    json.dumps({"results": results})
                )
            if flag == "--file":
                Path(work, Path(value).name).write_text(json.dumps({"matches": []}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class TestSeededReports(unittest.TestCase):
    def test_each_engine_seeds_the_reports_its_nodes_build(self):
        self.assertEqual(
            {
                engine: seed_reports.seeded_reports(engine)
                for engine in ("osv", "trivy", "grype", "")
            },
            {
                "osv": ("osv", "runtime.grype"),
                "trivy": ("runtime.grype",),
                "grype": (),
                "": (),
            },
        )


class TestSeedReports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed = self.root / pipeline().SBOM_SEED
        self.seed.mkdir()
        for path in (
            self.root / "osv" / "osv-scalibr" / "npm.zip",
            self.root / "grype" / "6" / "vulnerability.db",
        ):
            path.parent.mkdir(parents=True)
            path.write_text("db")
        self.entry = Entry("mirror/php", "sha256:" + "d" * 64, LAYERS, 42)
        syft_path, cyclonedx_path = seed_reports.seed_sbom_paths(self.seed, self.entry)
        syft_path.write_text(json.dumps(SYFT))
        cyclonedx_path.write_text(json.dumps(CYCLONEDX))

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self):
        docker = FakeDocker()
        stored = seed_reports.seed_reports(
            [self.entry], self.seed, self.root, ("osv", "runtime.grype"), IMAGES, docker
        )
        return stored, docker

    def test_the_seeded_reports_carry_the_fingerprints_a_node_computes(self):
        stored, _docker = self._seed()
        p = pipeline()
        node = p.Layout(
            runtime=("container", "run"),
            databases=self.root,
            sbom=self.root,
            work=self.root,
            excludes=(),
        )
        other_node_target = p.Target(
            "e" * 64, "container", "sha256:" + "e" * 64, "x", (), ()
        )
        expected = {
            "osv": p.sbom_report_fingerprint(
                node,
                "osv",
                p.layer_key(ENGINE_LAYERS["osv:1"]),
                p.osv_args(seed_reports.node_config(), ""),
                p.osv_identity(p.osv_sbom(CYCLONEDX)),
            ),
            "runtime.grype": p.sbom_report_fingerprint(
                node,
                "grype",
                p.layer_key(ENGINE_LAYERS["grype:1"]),
                p.match_args(p.runtime_args(other_node_target)),
                p.syft_identity(p.runtime_sbom(SYFT)),
            ),
        }
        self.assertEqual(
            (
                stored,
                {
                    name: _fingerprint(
                        seed_reports.report_path(self.seed, self.entry, name)
                    )
                    for name in expected
                },
            ),
            ({"osv": 1, "runtime.grype": 1}, expected),
        )

    def test_a_seeded_entry_is_not_scanned_again(self):
        self._seed()
        stored, docker = self._seed()
        self.assertEqual((stored, docker.calls), ({"osv": 0, "runtime.grype": 0}, []))

    def test_the_work_directory_is_removed(self):
        self._seed()
        self.assertEqual(
            sorted(path.name for path in self.seed.iterdir() if path.is_dir()), []
        )


if __name__ == "__main__":
    unittest.main()
