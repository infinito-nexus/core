from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito import memory as handler

STATIC = dict.fromkeys(handler.KEYS, "0")
COMMENTS = {key: f"{key} comment" for key in handler.KEYS}


def _ctx(*, on_gha: bool = False, on_act: bool = False) -> BuildContext:
    return BuildContext(
        static=dict(STATIC),
        static_comments=dict(COMMENTS),
        repo_root=Path("/repo"),
        on_gha=on_gha,
        on_act=on_act,
    )


def _applied(ctx: BuildContext, total_mb: int, env: dict[str, str]) -> EnvBuilder:
    eb = EnvBuilder()
    with (
        patch.dict("os.environ", env, clear=True),
        patch.object(handler, "mem_total_mb", return_value=total_mb),
    ):
        handler.apply(eb, ctx)
    return eb


class TestHostShare(unittest.TestCase):
    def test_a_workstation_gets_three_quarters_of_its_memory(self) -> None:
        with patch.object(handler, "mem_total_mb", return_value=65536):
            self.assertEqual(handler.host_share(_ctx()), "49152m")

    def test_ci_runs_get_no_cap(self) -> None:
        for ctx in (_ctx(on_gha=True), _ctx(on_act=True)):
            with (
                self.subTest(on_gha=ctx.on_gha, on_act=ctx.on_act),
                patch.object(handler, "mem_total_mb", return_value=65536),
            ):
                self.assertEqual(handler.host_share(ctx), "")

    def test_an_unreadable_meminfo_gets_no_cap(self) -> None:
        with patch.object(handler, "mem_total_mb", return_value=0):
            self.assertEqual(handler.host_share(_ctx()), "")


class TestApply(unittest.TestCase):
    def test_both_keys_carry_the_same_share_so_no_swap_adds_to_it(self) -> None:
        eb = _applied(_ctx(), 65536, {})
        self.assertEqual(
            {key: eb.values[key] for key in handler.KEYS},
            dict.fromkeys(handler.KEYS, "49152m"),
        )
        self.assertEqual({key: eb.comments[key] for key in handler.KEYS}, COMMENTS)

    def test_ci_keeps_the_static_unlimited_value(self) -> None:
        for ctx in (_ctx(on_gha=True), _ctx(on_act=True)):
            with self.subTest(on_gha=ctx.on_gha, on_act=ctx.on_act):
                eb = _applied(ctx, 65536, {})
                self.assertEqual({key: eb.values[key] for key in handler.KEYS}, STATIC)

    def test_ci_without_a_static_value_writes_no_key(self) -> None:
        ctx = BuildContext(
            static={},
            static_comments={},
            repo_root=Path("/repo"),
            on_gha=True,
            on_act=False,
        )
        eb = _applied(ctx, 65536, {})
        self.assertEqual(set(handler.KEYS) & set(eb.values), set())

    def test_the_caller_env_wins_over_the_share(self) -> None:
        eb = _applied(_ctx(), 65536, {"INFINITO_MEM_LIMIT": "16g"})
        self.assertEqual(eb.values["INFINITO_MEM_LIMIT"], "16g")
        self.assertEqual(eb.values["INFINITO_MEMSWAP_LIMIT"], "49152m")


if __name__ == "__main__":
    unittest.main()
