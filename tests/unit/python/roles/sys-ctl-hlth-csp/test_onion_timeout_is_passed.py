import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "sys-ctl-hlth-csp" / "tasks" / "00_core.yml"
_TOR_BRANCH = re.compile(r"--tor-proxy=.{0,200}?--onion-timeout=", re.DOTALL)
_START_BUDGET = re.compile(
    r"timeout_start_sec_for_domains\(\s*onion_per_domain_seconds=", re.DOTALL
)


class TestOnionTimeoutIsPassed(unittest.TestCase):
    def test_the_tor_branch_also_carries_the_onion_budget(self) -> None:
        self.assertRegex(
            read_text(str(TASKS)),
            _TOR_BRANCH,
            "the service reaches onion vhosts over Tor, where the checker's own "
            "20 s navigation budget expires before a heavy page finishes; pass "
            "--onion-timeout wherever --tor-proxy is passed",
        )

    def test_the_unit_start_budget_knows_the_onion_rate(self) -> None:
        self.assertRegex(
            read_text(str(TASKS)),
            _START_BUDGET,
            "TimeoutStartSec defaults to 25 s per domain, which an onion vhost "
            "with a multiplied navigation budget outlasts; systemd then kills "
            "the check mid-run instead of letting it report",
        )


if __name__ == "__main__":
    unittest.main()
