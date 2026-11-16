from __future__ import annotations

import os
import re
from unittest import TestCase, main

from utils.security import pipeline


class TestPipeline(TestCase):
    def test_the_role_script_loads_once(self):
        self.assertIs(pipeline.pipeline(), pipeline.pipeline())

    def test_every_engine_has_a_semver_pin(self):
        for engine in pipeline.pipeline().ENGINES:
            with self.subTest(engine=engine):
                self.assertRegex(
                    pipeline.engine_image(engine),
                    re.compile(r"^ghcr\.io/.+:v?\d+\.\d+\.\d+$"),
                )

    def test_the_engines_run_as_the_calling_user(self):
        self.assertEqual(pipeline.user_runtime()[-1], f"{os.getuid()}:{os.getgid()}")

    def test_the_role_default_is_a_valid_scan_config(self):
        services = pipeline.role_services()
        runtime = services["runtime"]
        keys = ("targets", "engines", "severity", "fixed_only", "workers", "db_update")
        config = pipeline.pipeline().scan_config(
            {
                **{key: runtime[key] for key in keys},
                "trivy_unmatched_os": services["trivy"]["unmatched_os"],
            }
        )
        self.assertLessEqual(
            set(config.severity.values()), set(pipeline.pipeline().ACTIONS)
        )


if __name__ == "__main__":
    main()
