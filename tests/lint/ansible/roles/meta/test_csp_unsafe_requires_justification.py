"""Flag ``unsafe-*: true`` grants in ``roles/<role>/meta/csp.yml`` that
carry no justification.

Every ``unsafe-*`` flag hands a piece of the Content-Security-Policy
back to the attacker: ``unsafe-inline`` re-admits inline ``<script>`` /
``style`` payloads, which is exactly the execution path an XSS needs,
and ``unsafe-eval`` re-admits string-to-code execution. Both are
routinely copied in to make a console error disappear and then stay for
years, long after the upstream app stopped needing them. A grant
therefore MUST carry a written reason naming what breaks without it.

Convention
==========
On the ``unsafe-*: true`` line itself, so the reason cannot drift to a
neighbouring directive:

    unsafe-inline: true # nocheck: csp-unsafe  Reason: <what breaks without it>

The ``nocheck`` opts into the exemption; the ``Reason:`` states why.
Both are required, in either order.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_CSP

from . import PROJECT_ROOT

_RULE = "csp-unsafe"

_UNSAFE = re.compile(r"^\s*unsafe-[a-z-]+\s*:\s*true\b")
_REASON = re.compile(r"#.*\breason\b\s*:\s*\S", re.IGNORECASE)


class TestCspUnsafeRequiresJustification(unittest.TestCase):
    def test_unsafe_flags_are_justified(self) -> None:
        findings: list[str] = []
        for path in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_CSP}")):
            try:
                lines = read_text(str(path)).splitlines()
            except (OSError, ValueError):
                continue
            rel = path.relative_to(PROJECT_ROOT).as_posix()

            for no, line in enumerate(lines, start=1):
                if not _UNSAFE.match(line):
                    continue
                missing = []
                if not line_has_rule(line, _RULE):
                    missing.append(f"# nocheck: {_RULE}")
                if not _REASON.search(line):
                    missing.append("Reason: <what breaks without it>")
                if missing:
                    findings.append(f"{rel}:{no}: missing {', '.join(missing)}")

        if findings:
            self.fail(
                f"{len(findings)} unjustified CSP relaxation(s). An "
                "'unsafe-*' flag re-opens the attack surface the policy "
                "exists to close, so it MUST NOT be set on suspicion or "
                "copied from another role: verify against the running app "
                "that the flag is really necessary, then record what "
                "breaks without it.\n\n"
                "Fix: state the verified reason on the flag's own line:\n\n"
                f"    unsafe-inline: true # nocheck: {_RULE}  Reason: "
                "<what breaks without it>\n\n"
                "Offenders:\n" + "\n".join(f"  - {f}" for f in findings)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
