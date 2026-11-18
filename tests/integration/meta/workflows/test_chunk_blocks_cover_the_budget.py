from __future__ import annotations

import math
import re
import unittest

from cli.meta.ci import matrix, query, slots
from cli.meta.roles.applications.new_in_branch import new_application_roles
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.github.variant import axes, network, pools, vpn
from utils.roles.display import display_names

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-orchestrator.yml"


def _job_list_rows() -> int:
    codec = display_names()
    entries = matrix.entries_of(
        modes=query.resolve_modes(query.ALL_MODES),
        whitelist=codec.decode_list(""),
        priority=codec.decode_list(
            " ".join(new_application_roles(PROJECT_ROOT / "roles"))
        ),
        lifecycles="",
        sweep=axes.resolve_sweep(),
        network_input=network.resolve_network_input(None),
        vpn_mode=vpn.resolve_vpn_mode(None),
        distros=pools.resolve_distros(""),
        filesystems=pools.resolve_filesystems(""),
        architectures=pools.resolve_architectures(""),
    )
    return sum(len(chunk) for chunk in matrix.chunks_of(entries, 0))


class TestChunkBlocksCoverTheBudget(unittest.TestCase):
    def test_the_declared_block_count_matches_the_orchestrator(self) -> None:
        jobs = load_yaml_any(str(WORKFLOW))["jobs"]
        declared = [
            name for name in jobs if re.fullmatch(r"test-deploy-chunk-\d+", name)
        ]
        self.assertEqual(
            len(declared),
            slots.chunk_blocks(),
            "INFINITO_CI_MAX_CHUNKS must equal the chunk jobs call-orchestrator.yml "
            "declares; a plan larger than the chain silently drops its tail",
        )

    def test_a_short_priority_chunk_strands_no_budget(self) -> None:
        rows = slots.available()
        if rows is None:
            rows = _job_list_rows()
        filled = math.ceil(rows / slots.chunk_size())
        self.assertGreaterEqual(
            slots.chunk_blocks(),
            filled + 1,
            f"a priority chunk shorter than a block still occupies one, so the "
            f"{rows} rows a sweep plans need a block beyond the {filled} they fill",
        )


if __name__ == "__main__":
    unittest.main()
