"""Forbid ``timeout-minutes`` above 345 in GitHub workflow files.

GitHub kills a hosted-runner job hard at 360 minutes (6h). A job or step
budgeted above 345 leaves the post-failure steps (rescue diagnostics,
artifact uploads) too little runtime: the platform kill fires before or
together with the configured timeout and the failure logs are lost.
Budget at most 345 so ``if: failure()`` / ``if: always()`` steps keep
enough headroom to extract them.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"

_MAX_TIMEOUT_MINUTES = 345

_TIMEOUT = re.compile(r"^\s*timeout-minutes:\s*(\d+)\b")


class TestWorkflowTimeoutHeadroom(unittest.TestCase):
    def test_timeouts_leave_extraction_headroom(self) -> None:
        offenders: list[str] = []
        for path in sorted(_WORKFLOWS_DIR.glob("*.yml")):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            for lineno, line in enumerate(read_text(str(path)).splitlines(), 1):
                match = _TIMEOUT.match(line)
                if match and int(match.group(1)) > _MAX_TIMEOUT_MINUTES:
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")

        if offenders:
            self.fail(
                f"{len(offenders)} workflow timeout(s) above "
                f"{_MAX_TIMEOUT_MINUTES} minutes. GitHub hard-kills "
                "hosted-runner jobs at 360, so the post-failure "
                "diagnostics/upload steps never run and the failure logs "
                f"are lost. Set at most {_MAX_TIMEOUT_MINUTES} to keep "
                "extraction headroom.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
