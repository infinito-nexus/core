"""Unit tests for the deploy-side matrix iteration in
`cli.deploy.development.deploy.handler`.

The init step builds N inventory folders (one per round, with the
per-app variant data baked in); the deploy handler re-derives the same
plan via `plan_dev_inventory_matrix` and deploys against each folder in
turn, purging only the apps whose variant changed between rounds. These
tests pin both the iteration order and the cleanup decisions."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# deploy.handler reads the running container name strictly via
# cli.deploy.development.common.resolve_container (which is sourced from
# scripts/meta/env/defaults.sh — the single SPOT for the formula). Patch
# that resolver for the whole test module instead of duplicating the
# formula or hard-coding INFINITO_CONTAINER in os.environ. The tests
# below do not assert on the returned value; the sentinel is purely an
# opaque fixture string.
_RESOLVE_CONTAINER_PATCHER = patch(
    "cli.deploy.development.deploy.resolve_container",
    return_value="<unit-test fixture>",
)
_RESOLVE_CONTAINER_PATCHER.start()

from cli.deploy.development.deploy import handler  # noqa: E402


def _args(
    *,
    apps: list[str] | None = None,
    variant: int | None = None,
    full_cycle: bool = False,
) -> argparse.Namespace:
    # `distro` is intentionally absent: deploy.handler no longer consumes
    # it (the --distro arg was retired in favour of resolve_distro() reading
    # INFINITO_DISTRO env strictly).
    return argparse.Namespace(
        inventory_dir="/srv/inv",
        apps=None,
        id=apps,
        debug=False,
        variant=variant,
        full_cycle=full_cycle,
        ansible_args=[],
    )


def _entry(
    round_index: int,
    inv_dir: str,
    round_variants: dict[str, int],
    include: tuple[str, ...] | None = None,
) -> tuple[int, str, dict[str, int], tuple[str, ...]]:
    """Build a 4-tuple plan entry. Defaults `include` to the keys of
    `round_variants` so existing test fixtures stay terse — round 0 of
    the deploy loop deploys whatever is in include, and the variant-aware
    planner naturally emits the same set."""
    if include is None:
        include = tuple(round_variants.keys())
    return (round_index, inv_dir, round_variants, include)


def _make_compose_mock() -> MagicMock:
    compose = MagicMock()
    compose.repo_root = Path("/tmp/infinito-nexus")
    return compose


class TestHandlerMatrixDeploy(unittest.TestCase):
    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_single_round_skips_matrix_loop(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv", {"web-app-jira": 0, "web-app-keycloak": 0}),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-jira", "web-app-keycloak"]))

        self.assertEqual(rc, 0)
        # Single deploy against the unsuffixed folder, no cleanup.
        run_deploy_mock.assert_called_once()
        self.assertEqual(run_deploy_mock.call_args.kwargs["inventory_dir"], "/srv/inv")
        purge_mock.assert_not_called()

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_round_one_only_deploys_apps_with_real_variant_one(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        # User-spec example: variant 0 covers ALL apps, variant 1 only
        # exists for WordPress. Round 1 MUST therefore deploy ONLY
        # web-app-wordpress, NOT keycloak (which has no variant 1 and
        # would only fall back to variant 0 -- already deployed in round 0).
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-wordpress": 0, "web-app-keycloak": 0}),
            _entry(1, "/srv/inv-1", {"web-app-wordpress": 1, "web-app-keycloak": 0}),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-wordpress", "web-app-keycloak"]))

        self.assertEqual(rc, 0)
        self.assertEqual(run_deploy_mock.call_count, 2)
        round_one_deploy_ids = run_deploy_mock.call_args_list[1].kwargs["deploy_ids"]
        self.assertEqual(round_one_deploy_ids, ["web-app-wordpress"])
        # Keycloak MUST NOT be in the round-1 deploy_ids; it stays at the
        # state round 0 produced.
        self.assertNotIn("web-app-keycloak", round_one_deploy_ids)
        # Purge mirrors the deploy filter: only WP gets purged before
        # round 1 (Keycloak is not being re-deployed).
        purge_mock.assert_called_once()
        self.assertEqual(purge_mock.call_args.kwargs["app_ids"], ["web-app-wordpress"])

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_two_round_plan_deploys_each_folder_in_order(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0, "web-app-keycloak": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1, "web-app-keycloak": 0}),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-multi", "web-app-keycloak"]))

        self.assertEqual(rc, 0)
        self.assertEqual(run_deploy_mock.call_count, 2)
        self.assertEqual(
            [c.kwargs["inventory_dir"] for c in run_deploy_mock.call_args_list],
            ["/srv/inv-0", "/srv/inv-1"],
        )
        # Per the spec ("der 1. eintrag auch im 2. durchlauf"): keycloak
        # stays on variant 0 in round 2, so it MUST NOT be purged. Only
        # `web-app-multi` flipped variants between rounds.
        purge_mock.assert_called_once()
        self.assertEqual(purge_mock.call_args.kwargs["app_ids"], ["web-app-multi"])

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_three_round_plan_only_re_deploys_apps_with_real_variant(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        # WordPress 2 variants, Discourse 3 variants, Keycloak 1 variant.
        # Round 0 deploys the full include set as the baseline.
        # Round 1: WP and Discourse have a real variant 1 -> both re-deploy.
        # Round 2: only Discourse has a real variant 2 -> only it re-deploys.
        # WordPress stays at variant 1 from round 1 (it has no variant 2);
        # Keycloak stays at variant 0 from round 0 (no later variants).
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(
                0,
                "/srv/inv-0",
                {"web-app-wordpress": 0, "web-app-discourse": 0, "web-app-keycloak": 0},
            ),
            _entry(
                1,
                "/srv/inv-1",
                {"web-app-wordpress": 1, "web-app-discourse": 1, "web-app-keycloak": 0},
            ),
            _entry(
                2,
                "/srv/inv-2",
                {"web-app-wordpress": 0, "web-app-discourse": 2, "web-app-keycloak": 0},
            ),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(
            _args(
                apps=[
                    "web-app-wordpress",
                    "web-app-discourse",
                    "web-app-keycloak",
                ]
            )
        )

        self.assertEqual(rc, 0)
        self.assertEqual(run_deploy_mock.call_count, 3)

        per_round_deploy_ids = [
            c.kwargs["deploy_ids"] for c in run_deploy_mock.call_args_list
        ]
        # Round 0: full baseline (mirrors `--id` order from _args).
        self.assertEqual(
            per_round_deploy_ids[0],
            ["web-app-wordpress", "web-app-discourse", "web-app-keycloak"],
        )
        # Round 1: WP + Discourse (their real variant index for the round).
        self.assertEqual(
            per_round_deploy_ids[1],
            ["web-app-discourse", "web-app-wordpress"],
        )
        # Round 2: only Discourse has variant 2.
        self.assertEqual(per_round_deploy_ids[2], ["web-app-discourse"])

        # Purge mirrors the per-round deploy filter:
        # Round 1 -> purge {WP, Discourse} (both flipped 0->1).
        # Round 2 -> purge {Discourse} (1->2). WP is NOT purged because it
        # is not being re-deployed this round; its round-1 state stays.
        self.assertEqual(purge_mock.call_count, 2)
        self.assertEqual(
            purge_mock.call_args_list[0].kwargs["app_ids"],
            ["web-app-discourse", "web-app-wordpress"],
        )
        self.assertEqual(
            purge_mock.call_args_list[1].kwargs["app_ids"],
            ["web-app-discourse"],
        )

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_failure_in_round_one_aborts_before_round_two(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1}),
        ]
        run_deploy_mock.return_value = 17  # failure exit code

        rc = handler(_args(apps=["web-app-multi"]))

        self.assertEqual(rc, 17)
        # Round 1 ran, round 2 must NOT have been attempted.
        run_deploy_mock.assert_called_once()
        purge_mock.assert_not_called()


class TestHandlerVariantPin(unittest.TestCase):
    """`--variant <idx>` (or VARIANT env-var) pins the deploy to one
    specific round's folder, skipping inter-round cleanup. Use case:
    redeploying one variant without iterating the whole matrix."""

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_variant_one_runs_only_that_round_no_cleanup(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1}),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-multi"], variant=1))

        self.assertEqual(rc, 0)
        # Only the picked round runs; no cleanup because there is no
        # previous round to diff against in single-round mode.
        run_deploy_mock.assert_called_once()
        self.assertEqual(
            run_deploy_mock.call_args.kwargs["inventory_dir"], "/srv/inv-1"
        )
        purge_mock.assert_not_called()

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_variant_out_of_range_exits_with_clean_message(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        _purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1}),
        ]

        with self.assertRaisesRegex(SystemExit, "variant 7 out of range"):
            handler(_args(apps=["web-app-multi"], variant=7))
        run_deploy_mock.assert_not_called()


class TestHandlerFullCycle(unittest.TestCase):
    """`--full-cycle` runs an async re-deploy IMMEDIATELY after each
    round's sync deploy (Pass 2 stays co-located with Pass 1 on the
    same variant). Without `--full-cycle` only Pass 1 runs per round."""

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_full_cycle_runs_pass2_after_each_round(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1}),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-multi"], full_cycle=True))

        self.assertEqual(rc, 0)
        # Two rounds, two passes each = 4 deploy calls.
        self.assertEqual(run_deploy_mock.call_count, 4)

        sequence = [
            (call.kwargs["inventory_dir"], call.kwargs.get("extra_ansible_vars"))
            for call in run_deploy_mock.call_args_list
        ]
        # Per-variant interleave: round-0 sync, round-0 async, then
        # round-1 sync, round-1 async.
        self.assertEqual(
            sequence,
            [
                ("/srv/inv-0", None),
                ("/srv/inv-0", {"ASYNC_ENABLED": True}),
                ("/srv/inv-1", None),
                ("/srv/inv-1", {"ASYNC_ENABLED": True}),
            ],
        )
        # Cleanup still runs once between rounds (variant changed 0->1).
        purge_mock.assert_called_once()

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_full_cycle_aborts_when_pass1_fails_skipping_pass2(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        _purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1}),
        ]
        # PASS 1 of round 0 fails. PASS 2 of round 0 and the entire round
        # 1 must be skipped to surface the failure cleanly.
        run_deploy_mock.return_value = 11

        rc = handler(_args(apps=["web-app-multi"], full_cycle=True))

        self.assertEqual(rc, 11)
        run_deploy_mock.assert_called_once()

    @patch("cli.deploy.development.deploy._purge_app_entities", autospec=True)
    @patch("cli.deploy.development.deploy._run_deploy", autospec=True)
    @patch("cli.deploy.development.deploy.plan_dev_inventory_matrix", autospec=True)
    @patch("cli.deploy.development.deploy.make_compose", autospec=True)
    def test_full_cycle_with_variant_pin_runs_only_one_round_with_both_passes(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        make_compose_mock.return_value = _make_compose_mock()
        plan_mock.return_value = [
            _entry(0, "/srv/inv-0", {"web-app-multi": 0}),
            _entry(1, "/srv/inv-1", {"web-app-multi": 1}),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-multi"], variant=1, full_cycle=True))

        self.assertEqual(rc, 0)
        self.assertEqual(run_deploy_mock.call_count, 2)
        sequence = [
            (call.kwargs["inventory_dir"], call.kwargs.get("extra_ansible_vars"))
            for call in run_deploy_mock.call_args_list
        ]
        self.assertEqual(
            sequence,
            [
                ("/srv/inv-1", None),
                ("/srv/inv-1", {"ASYNC_ENABLED": True}),
            ],
        )
        purge_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
