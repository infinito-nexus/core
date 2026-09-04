"""The committed MCP audit report matches a fresh generation.

A generated document that nobody regenerates becomes a snapshot of whenever
somebody last remembered, and it reads exactly like a current one. This report
answers "what does each surface expose, as whom, to whom" for reviewers who
will not open twenty-four ``meta/mcp.yml`` files, so a stale row is worse than
no row.

The check imports the generator and compares its output to the committed file
rather than reimplementing the rendering, so the two cannot disagree about what
"generated" means.

Fix a failure by regenerating and committing, never by editing the report.
"""

from __future__ import annotations

import importlib.util
import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_DOCS = PROJECT_ROOT / "docs" / "contributing" / "design" / "role" / "services" / "mcp"
_GENERATOR = _DOCS / "audit.gen.py"
_REPORT = _DOCS / "audit.md"


def _load_generator():
    spec = importlib.util.spec_from_file_location("mcp_audit_gen", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMcpAuditReport(unittest.TestCase):
    def test_the_committed_report_is_freshly_generated(self) -> None:
        rendered = _load_generator().render()
        committed = read_text(str(_REPORT))
        self.assertEqual(
            rendered,
            committed,
            f"{_REPORT.name} differs from a fresh generation. Regenerate and "
            f"commit it by running {_GENERATOR.name} from the repository root",
        )

    def test_the_report_carries_a_row_per_role_with_metadata(self) -> None:
        module = _load_generator()
        roles = sorted(
            p.parent.parent.name
            for p in module.ROLES_DIR.glob(f"*/{ROLE_FILE_META_MCP}")
        )
        self.assertTrue(
            roles,
            "no role owns meta/mcp.yml, so the report would be empty and this "
            "rule would pass vacuously",
        )
        committed = read_text(str(_REPORT))
        missing = [role for role in roles if f"`{role}`" not in committed]
        self.assertEqual(
            [],
            missing,
            "role(s) owning MCP metadata but absent from the report:\n"
            + "\n".join(f"  - {m}" for m in missing),
        )


if __name__ == "__main__":
    unittest.main()
