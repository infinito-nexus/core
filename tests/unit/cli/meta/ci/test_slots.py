from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from cli.meta.ci import slots


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _tree() -> TemporaryDirectory:
    tmp = TemporaryDirectory()
    root = Path(tmp.name)
    _write(
        root,
        slots._ORCHESTRATOR,
        """
        jobs:
          gate: {}
          build:
            needs: [gate]
          test-deploy-single-node:
            needs: [build]
            uses: ./.github/workflows/single-node.yml
          test-deploy-swarm:
            needs: [build]
            uses: ./.github/workflows/leaf.yml
          installs:
            needs: [gate]
            uses: ./.github/workflows/installs.yml
          done:
            needs: [test-deploy-single-node, test-deploy-swarm]
        """,
    )
    _write(
        root,
        ".github/workflows/single-node.yml",
        """
        jobs:
          compose:
            uses: ./.github/workflows/leaf.yml
          host:
            uses: ./.github/workflows/leaf.yml
        """,
    )
    _write(
        root,
        ".github/workflows/leaf.yml",
        """
        jobs:
          discover: {}
          deploy:
            strategy:
              matrix:
                include: ${{ fromJson(needs.discover.outputs.apps) }}
        """,
    )
    _write(
        root,
        ".github/workflows/installs.yml",
        """
        jobs:
          static:
            strategy:
              matrix:
                distro: [a, b, c]
          dynamic:
            strategy:
              matrix:
                include: ${{ fromJson(needs.x.outputs.y) }}
        """,
    )
    _write(
        root,
        ".github/workflows/entry-small.yml",
        """
        jobs:
          orchestrate:
            uses: ./.github/workflows/ci-orchestrator.yml
        """,
    )
    _write(
        root,
        ".github/workflows/entry-big.yml",
        """
        jobs:
          policy: {}
          release:
            uses: ./.github/workflows/installs.yml
          orchestrate:
            uses: ./.github/workflows/ci-orchestrator.yml
        """,
    )
    return tmp


class TestReservedSlots(unittest.TestCase):
    def test_counts_the_whole_chain_but_not_deploy_matrices(self) -> None:
        with _tree() as tmp:
            self.assertEqual(
                slots.reserved_slots(Path(tmp)),
                2 + (3 + slots._DYNAMIC_MATRIX_ESTIMATE) + 1 + 2 + 1,
            )

    def test_deploy_caller_dynamic_matrices_reserve_nothing(self) -> None:
        with _tree() as tmp:
            root = Path(tmp)
            jobs = slots._jobs(slots._load_workflow(root / slots._ORCHESTRATOR))
            self.assertEqual(
                slots._job_slots(
                    root, jobs["test-deploy-single-node"], count_dynamic=False
                ),
                2,
            )
            self.assertEqual(
                slots._job_slots(root, jobs["test-deploy-swarm"], count_dynamic=False),
                1,
            )


class TestEntryOverhead(unittest.TestCase):
    def test_worst_entry_counts_jobs_around_its_orchestrator_call(self) -> None:
        with _tree() as tmp:
            self.assertEqual(
                slots.entry_overhead(Path(tmp)),
                1 + (3 + slots._DYNAMIC_MATRIX_ESTIMATE),
            )


class TestModeSlots(unittest.TestCase):
    def test_split_follows_shares(self) -> None:
        with _tree() as tmp:
            root = Path(tmp)
            budget = slots.reserved_slots(root) + slots.entry_overhead(root)
            with mock.patch.dict(
                "os.environ", {"INFINITO_CI_JOB_LIMIT": str(budget + 60)}
            ):
                result = slots.mode_slots(root)
        self.assertEqual(
            result,
            {
                mode: max(
                    60 * share // sum(slots._SHARES.values()), slots._MIN_MODE_SLOTS
                )
                for mode, share in slots._SHARES.items()
            },
        )

    def test_overrides_pin_a_mode_over_the_derived_value(self) -> None:
        with (
            _tree() as tmp,
            mock.patch.dict(slots._SLOT_OVERRIDES, {"swarm": 7}),
        ):
            result = slots.mode_slots(Path(tmp))
        self.assertEqual(result["swarm"], 7)
        self.assertNotIn("compose", slots._SLOT_OVERRIDES)

    def test_floor_when_chain_eats_the_budget(self) -> None:
        with (
            _tree() as tmp,
            mock.patch.dict("os.environ", {"INFINITO_CI_JOB_LIMIT": "5"}),
        ):
            result = slots.mode_slots(Path(tmp))
        self.assertTrue(all(v >= slots._MIN_MODE_SLOTS for v in result.values()))


class TestRenderMatrix(unittest.TestCase):
    def test_table_lists_every_job_and_the_totals(self) -> None:
        with (
            _tree() as tmp,
            mock.patch.object(slots, "PROJECT_ROOT", Path(tmp)),
            mock.patch.dict("os.environ", {"INFINITO_CI_JOB_LIMIT": "256"}),
        ):
            table = slots.render_matrix()
        reserved = 2 + (3 + slots._DYNAMIC_MATRIX_ESTIMATE) + 1 + 2 + 1
        self.assertIn("installs", table)
        self.assertRegex(table, rf"reserved\s+{reserved}\n")
        self.assertRegex(table, r"job limit \(INFINITO_CI_JOB_LIMIT\)\s+256\n")
        for mode, share in slots._SHARES.items():
            self.assertIn(f"{mode} (share {share})", table)


if __name__ == "__main__":
    unittest.main()
