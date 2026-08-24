"""Lint: a dnsmasq zone mapped to an IPv4 address MUST also answer AAAA locally.

``address=/<zone>/<ipv4>`` covers A records only. Every AAAA query for that
zone is forwarded upstream, so a resolver that cannot reach its upstreams
turns each lookup by a glibc caller into a full resolver timeout — 20s per
name in run 32538854067, which blew the request budget of the Playwright
suite while the browser (racing A against AAAA) stayed fast.

Cover the zone with any of: a second ``address=`` carrying an IPv6 literal,
``local=/<zone>/`` (authoritative, answers NODATA), or ``filter-AAAA``.

Suppress a legitimate exception with ``# nocheck: dnsmasq-aaaa`` on the same
line as the ``address=`` declaration.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

_RULE = "dnsmasq-aaaa"

_ADDRESS_RE = re.compile(r"^\s*address=/(?P<zone>[^/]+)/(?P<target>\S+)")
_FILTER_AAAA_RE = re.compile(r"^\s*filter-AAAA\b")

_GLOBS = (
    "compose/**/*.j2",
    "roles/*/templates/**/*.j2",
    "roles/*/files/**/*.conf",
    "scripts/**/*.sh",
)


def _local_re(zone: str) -> re.Pattern[str]:
    return re.compile(r"^\s*local=/" + re.escape(zone) + r"/")


def _address_re(zone: str) -> re.Pattern[str]:
    return re.compile(r"^\s*address=/" + re.escape(zone) + r"/(?P<target>\S+)")


class TestDnsmasqAaaaCoverage(unittest.TestCase):
    def test_ipv4_zones_answer_aaaa_locally(self) -> None:
        offenders: list[str] = []
        for glob in _GLOBS:
            for path in sorted(PROJECT_ROOT.glob(glob)):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                lines = read_text(str(path)).splitlines()
                if any(_FILTER_AAAA_RE.match(line) for line in lines):
                    continue
                for no, line in enumerate(lines, start=1):
                    match = _ADDRESS_RE.match(line)
                    if match is None or ":" in match.group("target"):
                        continue
                    if is_suppressed_at(lines, no, _RULE):
                        continue
                    zone = match.group("zone")
                    if any(_local_re(zone).match(other) for other in lines):
                        continue
                    if any(
                        ":" in found.group("target")
                        for found in (_address_re(zone).match(other) for other in lines)
                        if found is not None
                    ):
                        continue
                    offenders.append(f"{rel}:{no}: {line.strip()[:100]}")

        if offenders:
            self.fail(
                f"{len(offenders)} dnsmasq zone(s) mapped to IPv4 without a local "
                "AAAA answer. Every AAAA lookup for them leaves the resolver and "
                "costs the full upstream timeout when it cannot be reached. Add "
                "`local=/<zone>/`, an IPv6 `address=`, or `filter-AAAA`, or mark a "
                f"legitimate exception with `# nocheck: {_RULE}`:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
