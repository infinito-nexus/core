from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from cli.meta.ci.variant_split import __main__ as cli
from cli.meta.ci.variant_split import snapshot as snapshot_module
from utils.cache.files import read_text

from . import entry, record, row, snapshot

LOG = (
    "2026-11-06T10:00:00.0Z TASK [prepare the host] ***\n"
    "2026-11-06T10:00:10.0Z TASK [web-app-a : first] ***\n"
    "2026-11-06T10:01:00.0Z TASK [web-app-b : first] ***\n"
    "2026-11-06T10:02:00.0Z TASK [test-e2e-playwright : run] ***\n"
)


def _snap(*, with_b: bool = True, seed: str | None = None) -> dict:
    include = ["web-app-b", "web-app-a"] if with_b else ["web-app-a"]
    snap = snapshot(
        [row("web-app-a#0", 1), row("web-app-b#0", 2)],
        {"web-app-a#0": record(include), "web-app-b#0": record(["web-app-b"])},
        head=[entry("web-app-a#0")],
        jobs=["web-app-a#0"],
    )
    if seed is not None:
        snap["seed"] = seed
    return snap


def _json(path: str | Path) -> dict:
    return json.loads(read_text(str(path)))


class TestMain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _write(self, name: str, data: dict) -> str:
        path = self.tmp / name
        path.write_text(json.dumps(data))
        return str(path)

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def _compare(self, before: dict, after: dict) -> tuple[int, str, str]:
        return self._run(
            "compare",
            self._write("before.json", before),
            self._write("after.json", after),
            "--old",
            "web-app-a#0",
            "--split",
            "web-app-a#0",
        )

    def test_compare_of_a_snapshot_with_itself_exits_0(self) -> None:
        rc, out, _ = self._compare(_snap(), _snap())
        self.assertEqual((rc, out.splitlines()[0]), (0, "coverage kept: yes"))

    def test_negative_control_compare_exits_1_when_coverage_is_lost(self) -> None:
        rc, out, _ = self._compare(_snap(), _snap(with_b=False))
        self.assertEqual((rc, out.splitlines()[0]), (1, "coverage kept: NO"))

    def test_negative_control_compare_refuses_snapshots_of_two_seeds(self) -> None:
        rc, _, err = self._compare(_snap(), _snap(seed="7"))
        self.assertEqual(rc, 2)
        self.assertIn("must be one run id", err)

    def test_compare_writes_the_verdict_when_asked(self) -> None:
        out_path = self.tmp / "verdict.json"
        self._run(
            "compare",
            self._write("before.json", _snap()),
            self._write("after.json", _snap()),
            "--old",
            "web-app-a#0",
            "--split",
            "web-app-a#0",
            "--out",
            str(out_path),
        )
        self.assertTrue(_json(out_path)["kept"])

    def test_snapshot_passes_the_seed_and_records_it(self) -> None:
        out_path = self.tmp / "snap.json"
        with mock.patch.object(
            snapshot_module, "take", return_value=_snap(seed="42")
        ) as take:
            rc, _, _ = self._run(
                "snapshot", "--out", str(out_path), "--seed", "42", "--sweeps", "0,1"
            )
        take.assert_called_once_with([0, 1], seed="42")
        self.assertEqual((rc, _json(out_path)["seed"]), (0, "42"))

    def test_negative_control_snapshot_without_a_seed_is_a_usage_error(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            cli.main(["snapshot", "--out", str(self.tmp / "snap.json")])

    def _segments(self, runner: str, name: str) -> str:
        out_path = self.tmp / name
        self._run(
            "segments",
            self._write("snap.json", _snap()),
            "--row",
            "web-app-a#0",
            "--runner",
            runner,
            "--pass",
            "1=1:",
            "--log",
            str(self._log()),
            "--out",
            str(out_path),
        )
        return str(out_path)

    def _log(self) -> Path:
        path = self.tmp / "deploy.log"
        path.write_text(LOG)
        return path

    def test_segments_from_a_log_record_the_runner_and_the_seen_apps(self) -> None:
        data = _json(self._segments("fast", "seg.json"))
        self.assertEqual(data["runner"], "fast")
        self.assertEqual(data["passes"]["1"], {"web-app-a": 50.0, "web-app-b": 60.0})

    def test_negative_control_merge_of_two_runners_fails(self) -> None:
        fast = self._segments("fast", "fast.json")
        slow = self._segments("slow", "slow.json")
        rc, _, err = self._run("merge", fast, slow, "--out", str(self.tmp / "m.json"))
        self.assertEqual(rc, 2)
        self.assertIn("cannot be merged", err)

    def test_merge_of_one_runner_writes_the_joined_file(self) -> None:
        first = self._segments("fast", "a.json")
        second = self._segments("fast", "b.json")
        merged = self.tmp / "m.json"
        rc, _, _ = self._run("merge", first, second, "--out", str(merged))
        self.assertEqual((rc, _json(merged)["runner"]), (0, "fast"))

    def test_cost_prints_the_saving_per_row(self) -> None:
        seg = self._segments("fast", "seg.json")
        rc, out, _ = self._run(
            "cost",
            self._write("before.json", _snap()),
            self._write("after.json", _snap(with_b=False)),
            "--segments",
            seg,
            "--old",
            "web-app-a#0",
            "--split",
            "web-app-a#0",
        )
        self.assertEqual(rc, 0)
        self.assertIn("web-app-a#0: ", out)


if __name__ == "__main__":
    unittest.main()
