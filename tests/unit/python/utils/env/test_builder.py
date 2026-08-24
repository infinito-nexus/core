"""Unit tests for :mod:`utils.env.builder`.

Covers the orchestration layer:

* :class:`EnvBuilder` — setdefault/set/get semantics around the
  caller-env precedence and per-key comment recording.
* :class:`BuildContext` — dataclass shape, immutability.
* :func:`build_env` — walks ``ORDERED_HANDLERS`` so its output reflects
  every handler's contribution. Asserted at the registry level (every
  handler ran, no value got dropped, comments propagate end-to-end).
"""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder, build_env
from utils.env.handlers import ORDERED_HANDLERS, PASSTHROUGH_STATIC_KEYS


class TestEnvBuilderSetdefault(unittest.TestCase):
    def test_falls_back_to_value_when_env_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.setdefault("FOO", "bar"), "bar")
            self.assertEqual(eb.values["FOO"], "bar")

    def test_caller_env_wins_when_non_empty(self) -> None:
        with patch.dict("os.environ", {"FOO": "from-env"}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.setdefault("FOO", "default"), "from-env")
            self.assertEqual(eb.values["FOO"], "from-env")

    def test_empty_string_env_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {"FOO": ""}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.setdefault("FOO", "default"), "default")

    def test_whitespace_only_env_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {"FOO": "   "}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.setdefault("FOO", "default"), "default")

    def test_records_comment_first_time(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            eb.setdefault("K", "v", comment="why")
            self.assertEqual(eb.comments["K"], "why")

    def test_comment_first_wins(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            eb.setdefault("K", "v", comment="first")
            eb.setdefault("K", "v2", comment="second")
            self.assertEqual(eb.comments["K"], "first")

    def test_empty_comment_arg_does_not_register(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            eb.setdefault("K", "v")
            self.assertNotIn("K", eb.comments)


class TestEnvBuilderSet(unittest.TestCase):
    def test_unconditional_overwrite(self) -> None:
        with patch.dict("os.environ", {"FOO": "from-env"}, clear=True):
            eb = EnvBuilder()
            eb.set("FOO", "forced")
            self.assertEqual(eb.values["FOO"], "forced")

    def test_set_overwrites_previously_setdefault(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            eb.setdefault("FOO", "first")
            eb.set("FOO", "second")
            self.assertEqual(eb.values["FOO"], "second")

    def test_set_first_comment_wins(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            eb.set("K", "v1", comment="first")
            eb.set("K", "v2", comment="second")
            self.assertEqual(eb.comments["K"], "first")

    def test_set_returns_value(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.set("K", "v"), "v")


class TestEnvBuilderGet(unittest.TestCase):
    def test_reads_from_builder_first(self) -> None:
        with patch.dict("os.environ", {"FOO": "env"}, clear=True):
            eb = EnvBuilder()
            eb.set("FOO", "builder")
            self.assertEqual(eb.get("FOO"), "builder")

    def test_falls_back_to_os_environ(self) -> None:
        with patch.dict("os.environ", {"FOO": "env"}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.get("FOO"), "env")

    def test_missing_returns_empty_string(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            self.assertEqual(eb.get("MISSING"), "")


class TestBuildContext(unittest.TestCase):
    def test_dataclass_shape(self) -> None:
        ctx = BuildContext(
            static={"K": "v"},
            static_comments={"K": "c"},
            repo_root=Path("/repo"),
            on_gha=False,
            on_act=False,
        )
        self.assertEqual(ctx.static, {"K": "v"})
        self.assertEqual(ctx.static_comments, {"K": "c"})
        self.assertEqual(ctx.repo_root, Path("/repo"))
        self.assertFalse(ctx.on_gha)
        self.assertFalse(ctx.on_act)

    def test_is_frozen(self) -> None:
        ctx = BuildContext(
            static={},
            static_comments={},
            repo_root=Path("/"),
            on_gha=False,
            on_act=False,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ctx.on_gha = True  # type: ignore[misc]


class TestBuildEnvOrchestration(unittest.TestCase):
    """End-to-end smoke of build_env against a minimal static map.

    Mocks ``detect_gha_act`` so we don't depend on the host env, and
    mocks the inventory helper so the test never shells out.
    """

    def _clean_env(self) -> dict[str, str]:
        return {"PATH": "/usr/bin"}

    def test_passes_static_through_builder(self) -> None:
        with (
            patch.dict("os.environ", self._clean_env(), clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            static = {
                "INFINITO_DISTRO": "debian",
                "INFINITO_PULL_POLICY": "never",
            }
            eb = build_env(static, repo_root=Path("/repo"), comments={})
        self.assertEqual(eb.values["INFINITO_DISTRO"], "debian")
        self.assertEqual(eb.values["INFINITO_PULL_POLICY"], "never")

    def test_propagates_static_comments(self) -> None:
        with (
            patch.dict("os.environ", self._clean_env(), clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            static = {"INFINITO_DISTRO": "debian"}
            comments = {"INFINITO_DISTRO": "selected distro"}
            eb = build_env(static, repo_root=Path("/repo"), comments=comments)
        self.assertEqual(eb.comments["INFINITO_DISTRO"], "selected distro")

    def test_container_derived_from_distro(self) -> None:
        with (
            patch.dict("os.environ", self._clean_env(), clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            static = {"INFINITO_DISTRO": "arch"}
            eb = build_env(static, repo_root=Path("/repo"))
        self.assertEqual(eb.values["INFINITO_CONTAINER"], "infinito_nexus_arch")

    def test_caller_env_wins_over_static(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {**self._clean_env(), "INFINITO_DISTRO": "ubuntu"},
                clear=True,
            ),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            eb = build_env({"INFINITO_DISTRO": "debian"}, repo_root=Path("/repo"))
        self.assertEqual(eb.values["INFINITO_DISTRO"], "ubuntu")
        self.assertEqual(eb.values["INFINITO_CONTAINER"], "infinito_nexus_ubuntu")

    def test_gha_branch_skipped_locally(self) -> None:
        with (
            patch.dict("os.environ", self._clean_env(), clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            eb = build_env(
                {"INFINITO_BUILD": "1", "INFINITO_DISTRO": "debian"},
                repo_root=Path("/repo"),
            )
        self.assertNotIn("INFINITO_GHCR_MIRROR_PREFIX", eb.values)
        self.assertNotIn("INFINITO_IMAGE", eb.values)
        self.assertEqual(eb.values["INFINITO_BUILD"], "1")

    def test_gha_branch_emits_overrides(self) -> None:
        env = {
            **self._clean_env(),
            "GITHUB_REPOSITORY_OWNER": "owner",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(True, False)),
            patch(
                "utils.env.handlers.infinito.image_repository.run_helper",
                return_value="repo",
            ),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            static = {
                "INFINITO_BUILD": "0",
                "INFINITO_DISTRO": "debian",
                "INFINITO_PULL_POLICY": "never",
                "INFINITO_DOCKER_VOLUME": "docker",
                "INFINITO_GHCR_MIRROR_PREFIX": "mirror",
                "INFINITO_IMAGE_TAG": "latest",
            }
            eb = build_env(static, repo_root=Path("/repo"))
        self.assertEqual(eb.values["INFINITO_PULL_POLICY"], "always")
        self.assertEqual(eb.values["INFINITO_DOCKER_VOLUME"], "/mnt/docker")
        self.assertEqual(eb.values["GITHUB_REPOSITORY_OWNER"], "owner")
        self.assertIn("INFINITO_IMAGE", eb.values)
        self.assertTrue(eb.values["INFINITO_IMAGE"].startswith("ghcr.io/owner/repo/"))

    def test_walks_full_handler_chain(self) -> None:
        """Every handler in ORDERED_HANDLERS must be reachable; this
        guards against a registry entry that never runs."""
        called: list[str] = []
        real_handlers = list(ORDERED_HANDLERS)
        for h in real_handlers:
            orig_apply = h.apply

            def trace(eb, ctx, *, _orig=orig_apply, _name=h.__name__):
                called.append(_name)
                return _orig(eb, ctx)

            h.apply = trace  # type: ignore[assignment]
        try:
            with (
                patch.dict("os.environ", self._clean_env(), clear=True),
                patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
                patch(
                    "utils.env.handlers.infinito.inventory.run_helper",
                    return_value="",
                ),
            ):
                build_env({"INFINITO_DISTRO": "debian"}, repo_root=Path("/repo"))
        finally:
            for h in real_handlers:
                h.apply = (
                    h.apply.__wrapped__ if hasattr(h.apply, "__wrapped__") else h.apply
                )  # type: ignore[attr-defined]
        self.assertEqual(len(called), len(real_handlers))

    def test_returns_envbuilder_instance(self) -> None:
        with (
            patch.dict("os.environ", self._clean_env(), clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            eb = build_env({"INFINITO_DISTRO": "debian"}, repo_root=Path("/repo"))
        self.assertIsInstance(eb, EnvBuilder)

    def test_passthrough_static_keys_round_trip(self) -> None:
        """Keys named by PASSTHROUGH_STATIC_KEYS that are present in
        the static map must land in the builder verbatim."""
        with (
            patch.dict("os.environ", self._clean_env(), clear=True),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            sample = {
                "INFINITO_BIND_IP": "127.0.0.1",
                "INFINITO_MEM_LIMIT": "0",
                "INFINITO_DISTRO": "debian",
            }
            for k in sample:
                self.assertIn(k, PASSTHROUGH_STATIC_KEYS)
            eb = build_env(sample, repo_root=Path("/repo"))
        self.assertEqual(eb.values["INFINITO_BIND_IP"], "127.0.0.1")
        self.assertEqual(eb.values["INFINITO_MEM_LIMIT"], "0")


if __name__ == "__main__":
    unittest.main()
