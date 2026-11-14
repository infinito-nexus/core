from __future__ import annotations

import random
from unittest import TestCase, main

from utils.security import engine
from utils.security.pipeline import pipeline


class TestEnginesFor(TestCase):
    def test_every_pin_runs_behind_syft(self):
        for name in engine.SCANNERS:
            with self.subTest(engine=name):
                self.assertEqual(engine.engines_for(name), ["syft", name])

    def test_an_unknown_engine_is_rejected(self):
        with self.assertRaises(ValueError):
            engine.engines_for("clair")

    def test_every_pin_reads_the_grype_database(self):
        self.assertEqual(engine.databases_for("trivy"), ["trivy", "grype"])
        self.assertEqual(engine.databases_for("grype"), ["grype"])

    def test_the_ci_pool_matches_the_role_pipeline(self):
        self.assertEqual(engine.SCANNERS, pipeline().SCANNERS)

    def test_every_pin_is_a_valid_role_config(self):
        p = pipeline()
        for name in engine.SCANNERS:
            with self.subTest(engine=name):
                config = p.scan_config(
                    {
                        "targets": ["host", "container"],
                        "engines": engine.engines_for(name),
                        "severity": {"CRITICAL": "fail", "HIGH": "warn"},
                        "fixed_only": True,
                        "workers": 2,
                        "db_update": False,
                        "trivy_unmatched_os": [],
                    }
                )
                self.assertEqual(list(config.databases()), engine.databases_for(name))


class TestDrawEngine(TestCase):
    def test_a_draw_is_one_scanner(self):
        rng = random.Random(1)  # noqa: S311 - seeded draw, not crypto
        self.assertIn(engine.draw_engine(rng), engine.SCANNERS)

    def test_draws_cover_every_scanner(self):
        rng = random.Random(7)  # noqa: S311 - seeded draw, not crypto
        self.assertEqual(
            {engine.draw_engine(rng) for _ in range(60)}, set(engine.SCANNERS)
        )


class TestDeployOverrides(TestCase):
    def test_a_deploy_reads_provided_databases(self):
        runtime = engine.deploy_overrides("osv", "/opt/vulnerability-db")[engine.ROLE][
            "services"
        ]["runtime"]
        self.assertEqual(
            runtime,
            {
                "engines": ["syft", "osv"],
                "database_dir": "/opt/vulnerability-db",
                "db_update": False,
            },
        )


if __name__ == "__main__":
    main()
