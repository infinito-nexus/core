from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import passthrough as handler

_CALLER = {"INFINITO_POOL_JOB": "3", "INFINITO_POOL_RUNNER": "true"}


_DEFAULTS = {"INFINITO_POOL_JOB": "", "INFINITO_POOL_RUNNER": "false"}


def _written(static: dict[str, str]) -> dict[str, str]:
    eb = EnvBuilder()
    handler.apply(
        eb,
        BuildContext(
            static=static,
            static_comments={},
            repo_root=Path("/repo"),
            on_gha=False,
            on_act=False,
        ),
    )
    return eb.values


class TestPassthrough(unittest.TestCase):
    @patch.dict(os.environ, _CALLER)
    def test_a_job_id_exported_for_one_make_call_is_not_written(self) -> None:
        self.assertEqual(_written(_DEFAULTS)["INFINITO_POOL_JOB"], "")

    @patch.dict(os.environ, _CALLER)
    def test_a_static_key_keeps_the_caller_value(self) -> None:
        self.assertEqual(_written(_DEFAULTS)["INFINITO_POOL_RUNNER"], "true")

    @patch.dict(os.environ, _CALLER)
    def test_a_static_map_without_a_per_call_key_writes_none(self) -> None:
        self.assertNotIn("INFINITO_POOL_JOB", _written({}))


if __name__ == "__main__":
    unittest.main()
