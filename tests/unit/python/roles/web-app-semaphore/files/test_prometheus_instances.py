from __future__ import annotations

import io
import json
import tempfile
import unittest
import unittest.mock as mock
import urllib.error
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-semaphore/files/python/prometheus_instances.py"
WS = "ws-0a1b2c3d-0000-4000-8000-00000000000a"
OTHER = "ws-0a1b2c3d-0000-4000-8000-00000000000b"
URL = "http://127.0.0.1:8066/-/reload"


def _load():
    spec = spec_from_file_location("prometheus_instances", SCRIPT)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


instances = _load()


def content(host):
    return json.dumps(
        {"scrape_configs": [{"static_configs": [{"labels": {"instance": host}}]}]}
    )


def state(host, shared=True, workspace=WS):
    return {
        "workspace": workspace,
        "file": f"{workspace}__{host}.yml",
        "instance": host,
        "content": content(host) if shared else None,
    }


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Reloads:
    def __init__(self, fail=False):
        self.fail = fail
        self.urls = []

    def __call__(self, request, timeout):
        self.urls.append((request.full_url, request.method, timeout))
        if self.fail:
            raise urllib.error.URLError("connection refused")
        return Response()


def run(directory, desired, fail=False):
    reloads = Reloads(fail)
    state_file = directory.parent / "state.json"
    state_file.write_text(json.dumps(desired), encoding="utf-8")
    out = io.StringIO()
    code = instances.main(
        [
            "apply",
            "--dir",
            str(directory),
            "--state",
            str(state_file),
            "--reload-url",
            URL,
        ],
        stdout=out,
        chown=lambda *_args: None,
        opener=reloads,
    )
    return code, json.loads(out.getvalue() or "null"), reloads.urls, state_file.exists()


class TestTheScrapeFile(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "instances"
        self.dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_new_target_is_written_private_and_reloads_once(self) -> None:
        code, outcome, reloads, staged = run(self.dir, state("target"))
        self.assertEqual(code, 0)
        self.assertEqual(outcome, {"changed": True, "kept": True, "reloaded": True})
        self.assertEqual(reloads, [(URL, "POST", instances.TIMEOUT)])
        written = self.dir / f"{WS}__target.yml"
        text = written.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertEqual(text, content("target"))
        self.assertEqual(written.stat().st_mode & 0o777, 0o640)
        self.assertFalse(staged)

    def test_a_second_apply_changes_nothing_and_does_not_reload(self) -> None:
        run(self.dir, state("target"))
        code, outcome, reloads, _ = run(self.dir, state("target"))
        self.assertEqual(
            (code, outcome["changed"], outcome["reloaded"], reloads),
            (0, False, False, []),
        )

    def test_a_host_that_stopped_sharing_loses_only_its_file(self) -> None:
        run(self.dir, state("target"))
        run(self.dir, state("other"))
        run(self.dir, state("target", workspace=OTHER))
        _, outcome, reloads, _ = run(self.dir, state("target", shared=False))
        self.assertEqual(outcome, {"changed": True, "kept": False, "reloaded": True})
        self.assertEqual(len(reloads), 1)
        self.assertEqual(
            sorted(path.name for path in self.dir.glob("*.yml")),
            [f"{WS}__other.yml", f"{OTHER}__target.yml"],
        )

    def test_remove_of_an_unknown_host_changes_nothing(self) -> None:
        code, outcome, reloads, _ = run(self.dir, state("target", shared=False))
        self.assertEqual((code, outcome["changed"], reloads), (0, False, []))

    def test_a_failed_reload_is_retried_by_the_next_run(self) -> None:
        marker = self.dir / f".{WS}__target.yml{instances.RELOAD_MARKER}"
        code, _, reloads, _ = run(self.dir, state("target"), fail=True)
        self.assertEqual((code, len(reloads)), (1, 1))
        self.assertTrue(marker.exists())
        code, outcome, reloads, _ = run(self.dir, state("target"))
        self.assertEqual(code, 0)
        self.assertEqual(outcome, {"changed": False, "kept": True, "reloaded": True})
        self.assertEqual(len(reloads), 1)
        self.assertFalse(marker.exists())

    def test_a_run_that_dies_after_the_change_reloads_on_the_next_run(self) -> None:
        marker = self.dir / f".{WS}__target.yml{instances.RELOAD_MARKER}"
        original = instances.reconcile

        def reconcile_then_die(*args):
            original(*args)
            raise KeyboardInterrupt

        for desired in (state("target"), state("target", shared=False)):
            with self.subTest(shared=desired["content"] is not None):
                with (
                    mock.patch.object(instances, "reconcile", reconcile_then_die),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    run(self.dir, desired)
                self.assertTrue(marker.exists())
                code, outcome, reloads, _ = run(self.dir, desired)
                self.assertEqual(
                    (code, outcome["changed"], len(reloads)), (0, False, 1)
                )
                self.assertFalse(marker.exists())

    def test_another_hosts_failed_reload_never_reloads_an_identical_apply(self) -> None:
        run(self.dir, state("target"))
        run(self.dir, state("other"), fail=True)
        code, outcome, reloads, _ = run(self.dir, state("target"))
        self.assertEqual((code, outcome["reloaded"], reloads), (0, False, []))

    def test_a_file_of_another_workspace_in_the_state_is_refused(self) -> None:
        desired = {**state("target"), "file": f"{OTHER}__target.yml"}
        code, outcome, reloads, staged = run(self.dir, desired)
        self.assertEqual((code, outcome, reloads), (1, None, []))
        self.assertFalse(staged)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_the_outcome_names_no_credential(self) -> None:
        desired = {**state("target"), "content": '{"credentials": "t0ken"}'}
        _, outcome, _, _ = run(self.dir, desired)
        self.assertNotIn("t0ken", json.dumps(outcome))


if __name__ == "__main__":
    unittest.main()
