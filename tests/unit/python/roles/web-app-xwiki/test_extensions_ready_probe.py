from __future__ import annotations

import unittest
from typing import Any

from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

PROBE = PROJECT_ROOT / "roles/web-app-xwiki/tasks/utils/extensions_ready.yml"
CORE_READ_REGISTER = "_xwiki_running_core"
SUPERADMIN = "superadmin"


def core_read_runs(probe_result: dict[str, Any]) -> bool:
    """Evaluate the core-version read's ``when`` list the way Ansible does.

    Args:
        probe_result: the registered result of the superadmin probe.

    Returns:
        ``True`` when every condition holds, stopping at the first false one.
    """
    tasks = load_yaml_str(read_text(str(PROBE)))
    task = next(t for t in tasks if t.get("register") == CORE_READ_REGISTER)
    env = Environment(autoescape=True)
    env.tests["skipped"] = lambda result: bool(result.get("skipped"))
    context = {
        "_xwiki_running": probe_result,
        "XWIKI_SUPERADMIN_USERNAME": SUPERADMIN,
    }
    return all(env.compile_expression(cond)(**context) for cond in task["when"])


class TestExtensionsReadyProbe(unittest.TestCase):
    def test_a_guest_answer_does_not_count_as_the_superadmin(self) -> None:
        self.assertFalse(
            core_read_runs({"status": 200, "changed": False}),
            "XWiki answers a rejected basic auth as guest with 200, so after a "
            "credential rotation the running wiki would pass the probe and the "
            "add-on check would PUT as guest and die on 401 after 31 retries",
        )

    def test_the_superadmin_answer_keeps_the_fast_path(self) -> None:
        self.assertTrue(
            core_read_runs({"status": 200, "xwiki_user": f"xwiki:XWiki.{SUPERADMIN}"}),
            "a probe XWiki answered as the superadmin must still reach the "
            "core-version read, or every unchanged redeploy pays two restarts",
        )

    def test_a_skipped_probe_never_reads_the_core(self) -> None:
        self.assertFalse(core_read_runs({"skipped": True, "changed": False}))


if __name__ == "__main__":
    unittest.main()
