"""Fail when a `ref:` pins a commit SHA that its upstream's newest release
tag contains.

A failed ``git ls-remote`` or ``git fetch`` counts as no such release, so an
unreachable remote never fails it.

Suppress a check by placing ``# nocheck: repository-version`` on the line
directly above the ``ref:`` key.
"""

from __future__ import annotations

import unittest

from utils.update.repository import find_outdated_updates, is_commit_sha

from . import PROJECT_ROOT


class TestShaPinsFollowTags(unittest.TestCase):
    def test_no_sha_pin_where_the_upstream_publishes_a_release(self) -> None:
        offenders = [
            f"{u.entry.config_path.relative_to(PROJECT_ROOT)}:{u.entry.line}: "
            f"{u.entry.repository} pins {u.entry.ref}, use the tag {u.latest}"
            for u in find_outdated_updates(PROJECT_ROOT)
            if is_commit_sha(u.entry.ref) and not is_commit_sha(u.latest)
        ]
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
