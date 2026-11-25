from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.gpu import count as handler

CONTEXT = BuildContext(
    static={},
    static_comments={},
    repo_root=Path("/repo"),
    on_gha=False,
    on_act=False,
)


def _apply(pinned: str, runtimes: str) -> tuple[EnvBuilder, int]:
    eb = EnvBuilder()
    with (
        patch.dict(os.environ, {handler.KEY: pinned}),
        patch.object(handler, "_runtimes", return_value=runtimes) as probe,
    ):
        handler.apply(eb, CONTEXT)
    return eb, probe.call_count


class TestGpuCount(unittest.TestCase):
    def test_a_pinned_count_never_asks_the_daemon(self) -> None:
        eb, probes = _apply("0", '{"nvidia": {}}')
        self.assertEqual(eb.values[handler.KEY], "0")
        self.assertEqual(probes, 0)

    def test_an_nvidia_runtime_reserves_every_gpu(self) -> None:
        eb, probes = _apply("", '{"nvidia": {}, "runc": {}}')
        self.assertEqual(eb.values[handler.KEY], "all")
        self.assertEqual(probes, 1)

    def test_a_daemon_without_nvidia_reserves_none(self) -> None:
        eb, _ = _apply("", '{"runc": {}}')
        self.assertEqual(eb.values[handler.KEY], "0")


if __name__ == "__main__":
    unittest.main()
