"""Unit tests for the deploy-side matrix iteration: each round deploys its own variant-closure (``include``); between rounds the wrapper wipes the union (``purge_set``)."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# deploy.handler reads the running container name strictly via
# cli.administration.deploy.development.common.resolve_container (which is sourced from
# scripts/meta/env/load.sh — the single SPOT for the formula). Patch
# that resolver for the whole test module instead of duplicating the
# formula or hard-coding INFINITO_CONTAINER in os.environ. The tests
# below do not assert on the returned value; the sentinel is purely an
# opaque fixture string.
_RESOLVE_CONTAINER_PATCHER = patch(
    "cli.administration.deploy.development.deploy.resolve_container",
    return_value="<unit-test fixture>",
)
_RESOLVE_CONTAINER_PATCHER.start()

from cli.administration.deploy.development.deploy import handler  # noqa: E402


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
    purge_set: tuple[str, ...] | None = None,
) -> tuple[int, str, dict[str, int], tuple[str, ...], tuple[str, ...]]:
    """5-tuple plan entry. Defaults: include=round_variants.keys(), purge_set=include — pass purge_set explicitly when round closures differ."""
    if include is None:
        include = tuple(round_variants.keys())
    if purge_set is None:
        purge_set = include
    return (round_index, inv_dir, round_variants, include, purge_set)


def _make_compose_mock() -> MagicMock:
    compose = MagicMock()
    compose.repo_root = Path("/tmp/infinito-nexus")
    return compose


class TestHandlerMatrixDeploy(unittest.TestCase):
    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
    def test_every_round_redeploys_full_include_after_purge(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        # Variant 0 covers BOTH apps, variant 1 only exists for WordPress.
        # Each round starts from a clean host (the previous round's full
        # include is purged), so round 1 redeploys the full round-1 include
        # — Keycloak included, even though it stays on variant 0 — because
        # the round-0 baseline was just purged away.
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
        self.assertEqual(
            sorted(round_one_deploy_ids),
            ["web-app-keycloak", "web-app-wordpress"],
        )
        # Purge runs once between rounds with the FULL previous round
        # include, not just variant-changed apps.
        purge_mock.assert_called_once()
        self.assertEqual(
            sorted(purge_mock.call_args.kwargs["app_ids"]),
            ["web-app-keycloak", "web-app-wordpress"],
        )

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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
        # Between rounds the FULL previous-round include is purged so
        # round 1 starts from a clean host — keycloak too, even though
        # it stays on variant 0.
        purge_mock.assert_called_once()
        self.assertEqual(
            sorted(purge_mock.call_args.kwargs["app_ids"]),
            ["web-app-keycloak", "web-app-multi"],
        )

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
    def test_three_round_plan_redeploys_full_include_each_round(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        # WordPress 2 variants, Discourse 3 variants, Keycloak 1 variant.
        # Each round starts from a clean host (full-include purge) and
        # therefore redeploys ITS OWN full include — keycloak too, even
        # though it has no later variants.
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

        full_include = ["web-app-discourse", "web-app-keycloak", "web-app-wordpress"]
        per_round_deploy_ids = [
            sorted(c.kwargs["deploy_ids"]) for c in run_deploy_mock.call_args_list
        ]
        for round_index, deploy_ids in enumerate(per_round_deploy_ids):
            self.assertEqual(
                deploy_ids, full_include, f"round {round_index} deploy_ids drifted"
            )

        # Purge runs between rounds with the FULL previous-round include.
        self.assertEqual(purge_mock.call_count, 2)
        for call in purge_mock.call_args_list:
            self.assertEqual(sorted(call.kwargs["app_ids"]), full_include)

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
    def test_round_transition_purges_union_when_variant_closures_differ(
        self,
        make_compose_mock: MagicMock,
        plan_mock: MagicMock,
        run_deploy_mock: MagicMock,
        purge_mock: MagicMock,
    ) -> None:
        # WHY: round 1 must deploy only its own closure (no coturn), yet the inter-round purge must wipe the union (coturn included).
        make_compose_mock.return_value = _make_compose_mock()
        union = ("web-app-nextcloud", "web-svc-coturn")
        plan_mock.return_value = [
            _entry(
                0,
                "/srv/inv-0",
                {"web-app-nextcloud": 0},
                include=("web-app-nextcloud", "web-svc-coturn"),
                purge_set=union,
            ),
            _entry(
                1,
                "/srv/inv-1",
                {"web-app-nextcloud": 1},
                include=("web-app-nextcloud",),
                purge_set=union,
            ),
        ]
        run_deploy_mock.return_value = 0

        rc = handler(_args(apps=["web-app-nextcloud"]))

        self.assertEqual(rc, 0)
        self.assertEqual(run_deploy_mock.call_count, 2)
        round_zero_deploy_ids = run_deploy_mock.call_args_list[0].kwargs["deploy_ids"]
        round_one_deploy_ids = run_deploy_mock.call_args_list[1].kwargs["deploy_ids"]
        self.assertEqual(
            sorted(round_zero_deploy_ids),
            ["web-app-nextcloud", "web-svc-coturn"],
        )
        self.assertEqual(round_one_deploy_ids, ["web-app-nextcloud"])
        purge_mock.assert_called_once()
        self.assertEqual(
            sorted(purge_mock.call_args.kwargs["app_ids"]),
            ["web-app-nextcloud", "web-svc-coturn"],
        )

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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
    """`--variant <idx>` (or variant env-var) pins the deploy to one
    specific round's folder, skipping inter-round cleanup. Use case:
    redeploying one variant without iterating the whole matrix."""

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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
        # round-1 sync, round-1 async. Every call carries the
        # zero-based VARIANT_INDEX so consumers like the
        # test-e2e-playwright role can namespace their artifacts.
        self.assertEqual(
            sequence,
            [
                ("/srv/inv-0", {"VARIANT_INDEX": 0}),
                ("/srv/inv-0", {"ASYNC_ENABLED": True, "VARIANT_INDEX": 0}),
                ("/srv/inv-1", {"VARIANT_INDEX": 1}),
                ("/srv/inv-1", {"ASYNC_ENABLED": True, "VARIANT_INDEX": 1}),
            ],
        )
        # Cleanup still runs once between rounds with the full
        # previous-round include.
        purge_mock.assert_called_once()
        self.assertEqual(purge_mock.call_args.kwargs["app_ids"], ["web-app-multi"])

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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

    @patch(
        "cli.administration.deploy.development.deploy._purge_app_entities",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy._run_deploy", autospec=True)
    @patch(
        "cli.administration.deploy.development.deploy.plan_dev_inventory_matrix",
        autospec=True,
    )
    @patch("cli.administration.deploy.development.deploy.make_compose", autospec=True)
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
                ("/srv/inv-1", {"VARIANT_INDEX": 1}),
                ("/srv/inv-1", {"ASYNC_ENABLED": True, "VARIANT_INDEX": 1}),
            ],
        )
        purge_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
