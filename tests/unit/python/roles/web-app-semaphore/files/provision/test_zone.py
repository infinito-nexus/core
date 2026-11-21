from __future__ import annotations

import contextlib
import io
import json
import unittest
import unittest.mock as mock
from pathlib import Path

from ._fake_provision import TempCase, load

zone = load("provision.zone")
VALUES_FILE = load("provision.session").VALUES_FILE


class PlantedSession:
    key = "SO-1/1.zone.tfstate"

    def __init__(self):
        self.destroyed = False

    def addresses(self):
        return [zone.ZONE_RESOURCE]

    def run(self, *_arguments, capture=False):
        resource = {"address": zone.ZONE_RESOURCE, "values": {"name": "a.example"}}
        return json.dumps({"values": {"root_module": {"resources": [resource]}}})

    def destroy(self):
        self.destroyed = True


class TestZoneDeleteWrite(TempCase):
    def setUp(self):
        super().setUp()
        self.task = self.root / "task"
        self.other = self.root / "other-run"
        for directory in (self.task, self.other):
            directory.mkdir()
            directory.chmod(zone.sandbox.TASK_MODE)
        self.values = self.task / VALUES_FILE
        self.victim = self.other / VALUES_FILE
        self.values.symlink_to(self.victim)

    def redirect_findings(self):
        """Returns:
        A finding when ``zone_delete`` of the runner wrote through the link a
        sandbox planted, into the other run's directory.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            zone.zone_delete(PlantedSession(), None, self.values, None)
        if self.victim.exists() or self.values.is_symlink():
            return [f"the write landed in {self.victim}"]
        return []

    def test_a_planted_symlink_never_redirects_a_runner_write(self):
        self.assertEqual(self.redirect_findings(), [])
        written = self.values.read_bytes()  # nocheck: cache-read tempdir
        self.assertEqual(json.loads(written), {"domain": "a.example"})

    def test_negative_control_a_following_write_lands_in_the_other_run(self):
        def following(task, relative, text):
            path = Path(task) / relative
            path.write_text(text, "utf-8")
            return path

        with mock.patch.object(zone.sandbox, "task_write", following):
            findings = self.redirect_findings()
        self.assertEqual(findings, [f"the write landed in {self.victim}"])


if __name__ == "__main__":
    unittest.main()
