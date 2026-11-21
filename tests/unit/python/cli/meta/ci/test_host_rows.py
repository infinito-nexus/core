from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout
from pathlib import Path

from cli.meta.ci import host_rows
from cli.meta.ci.host_rows import Closure, HostRow, rank
from cli.meta.roles.applications.complexity.model import (
    ComplexityRow,
    compute_variant_complexity_rows,
)
from utils.storage.constrained import StorageDeclarationError, closure_storage

from . import _host_fixture

_GB = 10**9


def _fixture_ranking(roles_dir: Path, tested: frozenset[str]) -> list[HostRow]:
    with mock.patch(
        "cli.meta.roles.applications.complexity.model._tested_apps",
        return_value=set(tested),
    ):
        rows = compute_variant_complexity_rows(roles_dir)
    static = {
        (row.name, row.variant): Closure(
            (row.name, *row.services), {row.name: row.variant}
        )
        for row in rows
    }
    return rank(
        rows,
        provider="svc-bkp-vault",
        mode="swarm",
        closure=lambda app, variant: static[(app, variant)],
        footprint=closure_storage(roles_dir),
    )


class TestRankOverFixtureRoles(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmp.name) / "roles"
        _host_fixture.build(self.roles_dir)
        self.ranking = _fixture_ranking(self.roles_dir, _host_fixture.APPS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_lightest_closure_ranks_first(self) -> None:
        self.assertEqual(
            [host.token for host in self.ranking],
            ["web-app-light#0", "web-app-bulky#1", "web-app-bulky#0"],
        )

    def test_top_row_leaves_the_heavy_provider_out(self) -> None:
        self.assertNotIn("svc-ai-heavy", self.ranking[0].roles)
        self.assertIn("svc-ai-heavy", self.ranking[-1].roles)

    def test_storage_is_the_closure_sum(self) -> None:
        self.assertEqual(
            [host.storage_bytes for host in self.ranking], [1 * _GB, 2 * _GB, 52 * _GB]
        )

    def test_rows_without_the_provider_are_no_hosts(self) -> None:
        apps = {host.app for host in self.ranking}
        self.assertNotIn("web-app-plain", apps)
        self.assertNotIn("svc-ai-heavy", apps)

    def test_host_mode_only_provider_has_no_row_of_its_own(self) -> None:
        self.assertNotIn("svc-bkp-vault", {host.app for host in self.ranking})

    def test_rows_untested_in_the_mode_are_skipped(self) -> None:
        ranking = _fixture_ranking(
            self.roles_dir, _host_fixture.APPS - {"web-app-light"}
        )
        self.assertEqual(
            [host.token for host in ranking], ["web-app-bulky#1", "web-app-bulky#0"]
        )


def _row(name: str, weight: int) -> ComplexityRow:
    return ComplexityRow(
        name, 0, [], 0, [], 0, [], 0, [], weight, "", [], variant=0, test_swarm=True
    )


class TestRankOrder(unittest.TestCase):
    def test_complexity_weight_breaks_a_storage_tie(self) -> None:
        ranking = rank(
            [_row("web-app-b", 9), _row("web-app-a", 3)],
            provider="svc-x",
            mode="swarm",
            closure=lambda app, variant: Closure((app, "svc-x"), {app: variant}),
            footprint=lambda roles, variants: dict.fromkeys(roles, 5),
        )
        self.assertEqual([host.app for host in ranking], ["web-app-a", "web-app-b"])

    def test_no_host_yields_an_empty_ranking(self) -> None:
        ranking = rank(
            [_row("web-app-a", 3)],
            provider="svc-x",
            mode="swarm",
            closure=lambda app, variant: Closure((app,), {app: variant}),
            footprint=lambda roles, variants: dict.fromkeys(roles, 5),
        )
        self.assertEqual(ranking, [])


class TestProviderRole(unittest.TestCase):
    def test_unknown_service_key_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            host_rows.provider_role("no-such-service-key")


class TestMain(unittest.TestCase):
    def _run(self, *argv: str) -> list[dict]:
        hosts = [
            HostRow("web-app-a", 0, ("web-app-a", "svc-x"), 1, 2),
            HostRow("web-app-b", 1, ("web-app-b", "svc-x"), 3, 4),
        ]
        out = io.StringIO()
        with (
            mock.patch.object(host_rows, "compute_variant_complexity_rows"),
            mock.patch.object(host_rows, "provider_role", return_value="svc-x"),
            mock.patch.object(host_rows, "closure_storage"),
            mock.patch.object(host_rows, "rank", return_value=hosts),
            redirect_stdout(out),
        ):
            self.assertEqual(host_rows.main(list(argv)), 0)
        return json.loads(out.getvalue())

    def test_json_lists_tokens_in_rank_order(self) -> None:
        payload = self._run("--provides", "x", "--mode", "swarm", "--format", "json")
        self.assertEqual(
            [entry["token"] for entry in payload], ["web-app-a#0", "web-app-b#1"]
        )

    def test_limit_cuts_the_ranking(self) -> None:
        payload = self._run(
            "--provides", "x", "--mode", "swarm", "--format", "json", "--limit", "1"
        )
        self.assertEqual([entry["token"] for entry in payload], ["web-app-a#0"])

    def test_an_unparsable_declaration_ends_the_ranking_by_name(self) -> None:
        with (
            mock.patch.object(host_rows, "compute_variant_complexity_rows"),
            mock.patch.object(host_rows, "provider_role", return_value="svc-x"),
            mock.patch.object(host_rows, "closure_storage"),
            mock.patch.object(
                host_rows,
                "rank",
                side_effect=StorageDeclarationError("web-app-odd: odd='plenty'"),
            ),
            self.assertRaisesRegex(SystemExit, "web-app-odd"),
        ):
            host_rows.main(["--provides", "x", "--mode", "swarm"])


class TestContainerBackupOnRealRoles(unittest.TestCase):
    """The real tree wired end to end on a few rows that embed container_backup.

    Which roles a real include set carries is a fact of the day; the fixture
    tests above are the contract. This only proves the real resolver, storage
    measure and ranking compose.
    """

    APPS = frozenset(
        {"web-app-wordpress", "web-app-gitea", "svc-db-openldap", "svc-db-mariadb"}
    )

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop("disable", None)
            cls.provider = host_rows.provider_role("container_backup")
            rows = [
                row
                for row in compute_variant_complexity_rows(host_rows.ROLES_DIR)
                if row.name in cls.APPS
            ]
            cls.ranking = rank(
                rows,
                provider=cls.provider,
                mode="swarm",
                closure=host_rows.swarm_closure,
                footprint=closure_storage(host_rows.ROLES_DIR),
            )

    def test_top_row_deploys_the_provider(self) -> None:
        self.assertTrue(self.ranking, "no real row hosts container_backup")
        self.assertIn(self.provider, self.ranking[0].roles)

    def test_top_row_is_lighter_than_the_heaviest_row(self) -> None:
        self.assertTrue(self.ranking, "no real row hosts container_backup")
        self.assertLess(self.ranking[0].storage_bytes, self.ranking[-1].storage_bytes)


class TestRoundVariantsCache(unittest.TestCase):
    def test_a_second_roles_tree_is_planned_on_its_own(self) -> None:
        def plan(*, roles_dir: str, **_: object) -> list[tuple]:
            return [(0, "plan", {"web-app-cached": len(roles_dir)}, (), ())]

        with mock.patch.object(
            host_rows, "plan_dev_inventory_matrix", side_effect=plan
        ):
            with mock.patch.object(host_rows, "ROLES_DIR", Path("/a")):
                first = host_rows.round_variants("web-app-cached", 0)
            with mock.patch.object(host_rows, "ROLES_DIR", Path("/a/bb")):
                second = host_rows.round_variants("web-app-cached", 0)
        self.assertEqual(
            (first, second), ({"web-app-cached": 2}, {"web-app-cached": 5})
        )


if __name__ == "__main__":
    unittest.main()
