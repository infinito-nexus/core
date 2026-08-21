# nocheck: workflow-references  synthetic fixture workflows, not repository files
from __future__ import annotations

import textwrap
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.meta.ci import slots

_SETTINGS = {
    "INFINITO_CI_JOB_LIMIT": "256",
    "INFINITO_CI_CONCURRENCY": "20",
    "INFINITO_CI_QUEUE_HOURS": "24",
    "INFINITO_CI_MAX_CHUNKS": "3",
}


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _tree(timeout: int = 355) -> TemporaryDirectory:
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
          test-deploy-chunk-0:
            needs: [build]
            uses: ./.github/workflows/call-test-deploy.yml
          test-deploy-chunk-1:
            needs: [test-deploy-chunk-0]
            uses: ./.github/workflows/call-test-deploy.yml
          installs:
            needs: [gate]
            uses: ./.github/workflows/installs.yml
          done:
            needs: [test-deploy-chunk-0, test-deploy-chunk-1]
        """,
    )
    _write(
        root,
        slots._DEPLOY_WORKFLOW,
        f"""
        jobs:
          discover: {{}}
          deploy:
            timeout-minutes: {timeout}
            strategy:
              matrix:
                include: ${{{{ fromJson(needs.discover.outputs.apps) }}}}
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
            uses: ./.github/workflows/call-orchestrator.yml
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
            uses: ./.github/workflows/call-orchestrator.yml
        """,
    )
    return tmp


class TestReservedSlots(unittest.TestCase):
    def test_counts_the_whole_chain_but_not_chunk_matrices(self) -> None:
        with _tree() as tmp:
            self.assertEqual(
                slots.reserved_slots(Path(tmp)),
                2 + 1 + 1 + (3 + slots._DYNAMIC_MATRIX_ESTIMATE) + 1,
            )

    def test_a_chunk_block_reserves_only_its_discover_job(self) -> None:
        with _tree() as tmp:
            root = Path(tmp)
            jobs = slots._jobs(slots._load_workflow(root / slots._ORCHESTRATOR))
            self.assertEqual(
                slots._job_slots(
                    root, jobs["test-deploy-chunk-0"], count_dynamic=False
                ),
                1,
            )

    def test_a_block_outside_the_chunk_prefix_is_charged_its_matrix(self) -> None:
        with _tree() as tmp:
            root = Path(tmp)
            jobs = slots._jobs(slots._load_workflow(root / slots._ORCHESTRATOR))
            self.assertEqual(
                slots._job_slots(root, jobs["test-deploy-chunk-0"], count_dynamic=True),
                1 + slots._DYNAMIC_MATRIX_ESTIMATE,
            )


class TestEntryOverhead(unittest.TestCase):
    def test_worst_entry_counts_jobs_around_its_orchestrator_call(self) -> None:
        with _tree() as tmp:
            self.assertEqual(
                slots.entry_overhead(Path(tmp)),
                1 + (3 + slots._DYNAMIC_MATRIX_ESTIMATE),
            )


class TestJobTimeout(unittest.TestCase):
    def test_read_from_the_deploy_workflow(self) -> None:
        with _tree(timeout=120) as tmp:
            self.assertEqual(slots.job_timeout_minutes(Path(tmp)), 120)

    def test_a_missing_timeout_fails_loudly(self) -> None:
        with _tree() as tmp:
            root = Path(tmp)
            _write(root, slots._DEPLOY_WORKFLOW, "jobs:\n  deploy: {}\n")
            with self.assertRaises(SystemExit):
                slots.job_timeout_minutes(root)


class TestChunkArithmetic(unittest.TestCase):
    def test_waves_fit_inside_the_queue_window(self) -> None:
        with _tree(timeout=355) as tmp, mock.patch.dict("os.environ", _SETTINGS):
            self.assertEqual(slots.waves(Path(tmp)), 4)
            self.assertEqual(slots.chunk_size(Path(tmp)), 80)

    def test_a_timeout_at_the_window_leaves_one_wave(self) -> None:
        with _tree(timeout=24 * 60) as tmp, mock.patch.dict("os.environ", _SETTINGS):
            self.assertEqual(slots.waves(Path(tmp)), 1)

    def test_a_timeout_beyond_the_window_still_leaves_one_wave(self) -> None:
        with _tree(timeout=30 * 60) as tmp, mock.patch.dict("os.environ", _SETTINGS):
            self.assertEqual(slots.waves(Path(tmp)), 1)

    def test_chunk_count_is_capped_by_the_declared_blocks(self) -> None:
        with (
            _tree() as tmp,
            mock.patch.dict("os.environ", {**_SETTINGS, "INFINITO_CI_MAX_CHUNKS": "2"}),
        ):
            self.assertEqual(slots.chunk_count(Path(tmp)), 2)

    def test_a_small_budget_needs_a_single_chunk(self) -> None:
        with (
            _tree() as tmp,
            mock.patch.dict("os.environ", {**_SETTINGS, "INFINITO_CI_JOB_LIMIT": "30"}),
        ):
            root = Path(tmp)
            self.assertEqual(slots.chunk_count(root), 1)
            self.assertEqual(slots.rows_per_sweep(root), slots.available(root))

    def test_rows_per_sweep_never_exceeds_the_run_job_cap(self) -> None:
        with _tree() as tmp, mock.patch.dict("os.environ", _SETTINGS):
            root = Path(tmp)
            self.assertLessEqual(slots.rows_per_sweep(root), slots.available(root))


class TestRenderMatrix(unittest.TestCase):
    def test_table_lists_every_job_and_the_chunk_arithmetic(self) -> None:
        with (
            _tree() as tmp,
            mock.patch.object(slots, "PROJECT_ROOT", Path(tmp)),
            mock.patch.dict("os.environ", _SETTINGS),
        ):
            table = slots.render_matrix()
        self.assertIn("installs", table)
        self.assertRegex(table, r"job limit \(INFINITO_CI_JOB_LIMIT\)\s+256\n")
        for row in ("chunk size", "chunks filled", "rows per sweep", "waves"):
            self.assertIn(row, table)


if __name__ == "__main__":
    unittest.main()
