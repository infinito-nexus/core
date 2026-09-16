"""Lint: a firewall fragment may tighten, never overrule.

A fragment declares its own nftables table. In nftables an ``accept`` verdict
terminates that table's base chain and nothing else: the packet still traverses
every other base chain registered at the same hook, and a ``drop`` in any of
them wins. Docker sets the filter FORWARD policy to ``drop`` by default, so a
fragment that accepts is not permitting anything, it is only declining to
decide.

Measured, not assumed: converting a role's ``iptables -A FORWARD -i wg0 -j
ACCEPT`` into a fragment rule at priority -10 dropped every forwarded packet
under that policy, 0 of 3 against 3 of 3 for the rule it replaced, with the
fragment's own counter showing the accept had matched all three. The deploy was
green either way.

A rule that has to overrule a policy another component set belongs in the chain
that carries that policy, not in a fragment.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: firewall-fragment-accept`` on the rule's line or the one above it,
  for an accept whose only job is to skip the fragment's own later rules.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "firewall-fragment-accept"
_FRAGMENT = "templates/nftables.conf.j2"
_POLICY = re.compile(r"\bpolicy\s+accept\b")
_VERDICT = re.compile(r"\baccept\s*$")


def _fragments() -> list[str]:
    suffix = "/" + _FRAGMENT
    return sorted(
        path
        for path in iter_project_files(extensions=(".j2",), exclude_tests=True)
        if path.endswith(suffix)
    )


class TestFirewallFragmentVerdicts(unittest.TestCase):
    def test_no_fragment_rule_accepts(self) -> None:
        findings: list[str] = []
        for path in _fragments():
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path).splitlines()
            for index, line in enumerate(lines):
                body = line.split("#")[0].rstrip().rstrip(";")
                if _POLICY.search(body) or not _VERDICT.search(body):
                    continue
                if is_suppressed_at(lines, index + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append(f"- {rel}:{index + 1}: {line.strip()}")

        if findings:
            self.fail(
                "These fragment rules end in an accept verdict, which terminates "
                "only this table's base chain. Another chain at the same hook can "
                "still drop the packet, so the rule permits nothing:\n"
                + "\n".join(findings)
                + "\n\nFix: express the intent as a drop of what must not pass, or "
                "put the rule in the chain that carries the policy it has to "
                f"overrule. Mark it `nocheck: {_RULE}` when the accept only skips "
                "the fragment's own later rules."
            )


if __name__ == "__main__":
    unittest.main()
