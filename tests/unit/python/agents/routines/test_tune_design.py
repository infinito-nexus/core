from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.routines import discover, tune_design
from agents.routines.tools import gallery
from cli.meta.roles.design import SPEC_FILE
from tests.unit.python.agents.routines.iterate import walk
from utils.design.proposal import PROPOSAL_FILE

_STEPS = {step.id: step for step in tune_design.STEPS}
_DESIGNED = "web-app-gitea"
_UNDESIGNED = "web-app-plain"


class TestScope(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        spec = root / "roles" / _DESIGNED / SPEC_FILE
        spec.parent.mkdir(parents=True)
        spec.write_text("", encoding="utf-8")
        (root / "roles" / _UNDESIGNED).mkdir(parents=True)
        patcher = patch.object(tune_design, "PROJECT_ROOT", root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _scope(self, **state: object) -> dict:
        return tune_design._scope(
            {"apps": [_DESIGNED, _UNDESIGNED, "svc-db-postgres"], **state}
        )

    def test_a_compose_run_with_design_on_captures_its_designed_web_roles(
        self,
    ) -> None:
        state = self._scope(mode="compose", disabled=["matomo"])
        self.assertEqual(
            (state["scope"], state["apps"]), (tune_design.DEPLOYED, [_DESIGNED])
        )

    def test_a_run_without_the_design_provider_captures_nothing(self) -> None:
        state = self._scope(mode="compose", disabled=["matomo", "design"])
        self.assertEqual((state["scope"], state["apps"]), (tune_design.NOTHING, []))

    def test_a_run_outside_compose_captures_nothing(self) -> None:
        for mode in ("swarm", ""):
            with self.subTest(mode=mode):
                state = self._scope(mode=mode)
                self.assertEqual(state["scope"], tune_design.NOTHING)

    def test_a_stub_run_reaches_done(self) -> None:
        visited, _ = walk(tune_design.STEPS, {})
        self.assertEqual(visited, ["scope", "done"])


class TestProposals(unittest.TestCase):
    def test_findings_are_filed_for_captured_apps_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for app in (_DESIGNED, _UNDESIGNED):
                (root / app).mkdir()
            with patch.object(tune_design, "GALLERY_ROOT", root):
                state = tune_design._propose(
                    {
                        "apps": [_DESIGNED],
                        "findings": {_DESIGNED: ["a"], _UNDESIGNED: ["b"]},
                    }
                )
            self.assertEqual(
                state["proposals"], {_DESIGNED: str(root / _DESIGNED / PROPOSAL_FILE)}
            )
            self.assertFalse((root / _UNDESIGNED / PROPOSAL_FILE).exists())


class TestShape(unittest.TestCase):
    def test_the_routine_is_discovered(self) -> None:
        self.assertIn("tune_design", discover())

    def test_capture_and_manifest_reuse_the_designer_gallery(self) -> None:
        self.assertIn(gallery.GALLERY_COMMAND, _STEPS["capture"].label)
        self.assertIn(gallery.MANIFEST_COMMAND, _STEPS["manifest"].label)
        self.assertIs(_STEPS["manifest"].fn, gallery.collect)

    def test_only_findings_leave_the_review(self) -> None:
        review = _STEPS["review"]
        self.assertEqual(review.kind, "model")
        self.assertEqual(review.output_schema, (("findings", dict),))
        self.assertEqual(
            dict(review.branches),
            {tune_design.CLEAN: "done", tune_design.PROPOSAL: "propose"},
        )

    def test_no_step_edits_or_commits(self) -> None:
        for step in tune_design.STEPS:
            with self.subTest(step=step.id):
                self.assertNotRegex(step.label, r"\bgit (commit|push)|compose-deploy")


if __name__ == "__main__":
    unittest.main()
