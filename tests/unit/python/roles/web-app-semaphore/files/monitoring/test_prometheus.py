from __future__ import annotations

import json
import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._fake_monitoring import (
    FILES,
    MODULES,
    SCRIPT,
    WS,
    RunError,
    planned_for,
    prometheus,
    removed_plan,
    target,
)

ROLE = FILES.parent


class TestThePrometheusTarget(unittest.TestCase):
    def test_monitoring_has_no_switch_that_skips_tls_verification(self) -> None:
        sources = [SCRIPT] + [
            FILES / "python" / "monitoring" / f"{name}.py" for name in MODULES
        ]
        for source in sources:
            with self.subTest(source=source.name):
                self.assertNotIn("TLS_VERIFY", read_text(str(source)))
        self.assertNotIn(
            "MONITOR_SCRAPE_TLS_VERIFY", read_text(str(ROLE / ROLE_FILE_VARS_MAIN))
        )

    def test_the_file_carries_the_token_labels_and_verification(self) -> None:
        state = prometheus.prometheus_state(planned_for(), "t0ken")
        self.assertEqual(state["file"], f"{WS}__target.yml")
        (job,) = json.loads(state["content"])["scrape_configs"]
        self.assertEqual(job["metrics_path"], "/federate")
        self.assertEqual(
            job["authorization"], {"type": "Bearer", "credentials": "t0ken"}
        )
        self.assertEqual(job["tls_config"], {"insecure_skip_verify": False})
        self.assertIs(job["follow_redirects"], False)
        self.assertEqual(
            job["static_configs"],
            [
                {
                    "targets": ["prometheus.target.example.org"],
                    "labels": {"workspace": WS, "instance": "target"},
                }
            ],
        )
        self.assertFalse(job["honor_labels"])

    def test_a_host_without_a_kind_and_remove_delete_the_file(self) -> None:
        quiet = planned_for(
            target=target({"health": False, "system": False, "traffic": False})
        )
        for planned in (quiet, removed_plan()):
            with self.subTest(action=planned["action"]):
                self.assertIsNone(prometheus.prometheus_state(planned, None)["content"])

    def test_a_sharing_host_without_a_token_fails(self) -> None:
        with self.assertRaises(RunError):
            prometheus.prometheus_state(planned_for(), None)


if __name__ == "__main__":
    unittest.main()
