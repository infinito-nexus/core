"""The stage loop skips roles no host carries, and gives every host one list.

Dropping what nobody deploys is free: 132 of 139 entries were skipped one task
at a time on a single-app deploy, 278 task deltas, 41.8 seconds measured on
2026-09-23.

Dropping what *this* host does not carry is not free, and these cases forbid
it. 8aea5a9b35 measured that a per-host condition above the loop makes ansible
insert blocks in host order rather than loop order, after which
svc-storage-nfs-client mounted an export svc-storage-nfs-server had not
deployed yet (run 31645153977). The list therefore has to come out identical
for every host, and per-host narrowing stays in the body's ``when``.
"""

from __future__ import annotations

import unittest
from typing import ClassVar
from unittest import mock

from plugins.lookup.group_roles import LookupModule

ENTRIES = [
    {"role": "web-app-alpha", "app": "alpha"},
    {"role": "web-app-beta", "app": "beta"},
    {"role": "web-app-gamma", "app": "gamma"},
]


def run(**kwargs):
    with mock.patch(
        "plugins.lookup.group_roles.ordered_roles", return_value=list(ENTRIES)
    ):
        return LookupModule().run(["web-app"], **kwargs)[0]


class TestWithoutAnInventory(unittest.TestCase):
    def test_no_groups_returns_the_whole_group(self) -> None:
        self.assertEqual(run(), ENTRIES)


class TestDroppingWhatNobodyDeploys(unittest.TestCase):
    def test_a_role_no_host_carries_is_dropped(self) -> None:
        selected = run(inventory_groups={"alpha": ["h1"], "beta": []})
        self.assertEqual([entry["app"] for entry in selected], ["alpha"])

    def test_an_empty_inventory_deploys_nothing(self) -> None:
        self.assertEqual(run(inventory_groups={}), [])

    def test_run_after_order_survives_the_filter(self) -> None:
        selected = run(inventory_groups={"gamma": ["h1"], "alpha": ["h1"]})
        self.assertEqual(
            [entry["app"] for entry in selected],
            ["alpha", "gamma"],
            "run_after order is the contract; the inventory's key order is not",
        )


class TestSameListForEveryHost(unittest.TestCase):
    """The property 8aea5a9b35 paid for; losing it inverts deploy order."""

    GROUPS: ClassVar[dict] = {"alpha": ["h1"], "beta": ["h2"], "gamma": ["h1", "h2"]}

    def test_a_role_only_one_host_carries_still_enters_the_loop(self) -> None:
        selected = [entry["app"] for entry in run(inventory_groups=self.GROUPS)]
        self.assertEqual(
            selected,
            ["alpha", "beta", "gamma"],
            "beta belongs to h2 only; dropping it for h1 would give the two "
            "hosts different loops and let host order decide item order",
        )

    def test_the_lookup_reads_no_per_host_variable(self) -> None:
        selected = run(inventory_groups=self.GROUPS, group_names=["alpha"])
        self.assertEqual(
            [entry["app"] for entry in selected],
            ["alpha", "beta", "gamma"],
            "a host's own groups must not reach this lookup; narrowing to one "
            "host belongs in the body's when",
        )


if __name__ == "__main__":
    unittest.main()
