from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.meta.ci.variant_split import snapshot
from utils.roles.mapping import ROLE_FILE_META_VARIANTS


def _candidates() -> list[dict]:
    return [
        {"name": "app", "variant": 0, "id": 1, "covered_by": 0, "clone": False},
        {"name": "dep", "variant": None, "id": 2, "covered_by": 1, "clone": False},
    ]


def _assign(rows: list, sweep: int) -> list[dict]:
    return [
        {
            "apps": r["name"],
            "variant": "" if r["variant"] is None else str(r["variant"]),
            "mode": "compose" if (i + sweep) % 2 == 0 else "swarm",
            "priority": "false",
            "covered": str(r["covered_by"]),
            "clone": "false",
            "id": str(r["id"]),
        }
        for i, r in enumerate(rows)
    ]


class TestAssemble(unittest.TestCase):
    def setUp(self) -> None:
        self.resolved = []
        self.snap = snapshot.assemble(
            candidates=_candidates(),
            sweeps=[0, 1],
            assign=_assign,
            head_of=lambda entries: entries[:1],
            is_regular=lambda e: e["covered"] == "0",
            resolve=lambda name, variant: (
                self.resolved.append((name, variant)) or {"include": [name]}
            ),
            budget={"available": 1},
            variant_counts={"app": 1},
            pins=[],
            digest="d",
            seed="42",
        )

    def test_every_candidate_is_resolved_once(self) -> None:
        self.assertEqual(self.resolved, [("app", 0), ("dep", None)])
        self.assertEqual(sorted(self.snap["rounds"]), ["app#0", "dep#0"])

    def test_each_sweep_keeps_its_own_rotation_head(self) -> None:
        self.assertEqual(self.snap["sweeps"]["0"]["head"][0]["mode"], "compose")
        self.assertEqual(self.snap["sweeps"]["1"]["head"][0]["mode"], "swarm")

    def test_the_job_list_keeps_only_regular_entries(self) -> None:
        self.assertEqual(self.snap["sweeps"]["0"]["jobs"], ["app#0"])

    def test_rows_keep_their_coverage_credit(self) -> None:
        self.assertEqual(self.snap["rows"][1]["covered_by"], 1)

    def test_the_snapshot_records_its_seed(self) -> None:
        self.assertEqual(self.snap["seed"], "42")


class TestSeeds(unittest.TestCase):
    def test_two_snapshots_of_one_run_id_share_it(self) -> None:
        self.assertEqual(snapshot.check_seeds({"seed": "7"}, {"seed": "7"}), "7")

    def test_negative_control_different_seeds_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be one run id"):
            snapshot.check_seeds({"seed": "7"}, {"seed": "8"})

    def test_negative_control_an_unseeded_snapshot_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            snapshot.check_seeds({}, {})

    def test_an_empty_seed_never_takes_a_snapshot(self) -> None:
        with (
            mock.patch.object(snapshot, "pipeline") as pipeline,
            self.assertRaises(ValueError),
        ):
            snapshot.take([0], seed=" ")
        pipeline.assert_not_called()

    def test_the_seed_is_exported_before_the_pipeline_ranks(self) -> None:
        seen = []

        def pipeline() -> dict:
            seen.append(os.environ[snapshot.SEED_ENV])
            raise RuntimeError

        with (
            mock.patch.dict(os.environ, {}),
            mock.patch.object(snapshot, "pipeline", pipeline),
            self.assertRaises(RuntimeError),
        ):
            snapshot.take([0], seed="42305502796")
        self.assertEqual(seen, ["42305502796"])


class TestDigest(unittest.TestCase):
    def test_negative_control_an_edited_variants_file_changes_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "role" / ROLE_FILE_META_VARIANTS
            path.parent.mkdir(parents=True)
            path.write_text("- {}\n")
            first = snapshot.variants_digest(tmp)
            path.write_text("- {}\n- {}\n")
            self.assertNotEqual(first, snapshot.variants_digest(tmp))


if __name__ == "__main__":
    unittest.main()
