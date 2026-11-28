from __future__ import annotations

import copy
import json
import unittest

from plugins.action.cloudflare_records_converged import JUDGED_TYPES
from tests.utils.cloudflare_apply import (
    MODULE,
    OMIT,
    SOLO_ABSENT,
    applying_tasks,
    module_rejections,
    role_tasks,
    solo_for_every_state,
)

ZONE = "example.org"
DS = {"key_tag": 2371, "algorithm": 13, "hash_type": 2, "value": "AB" * 32}
RECORDS = [
    {"type": "A", "zone": ZONE, "name": "www", "content": "192.0.2.1"},
    {"type": "AAAA", "zone": ZONE, "name": "www", "content": "2001:db8::1"},
    {
        "type": "AAAA",
        "zone": ZONE,
        "name": "ns1.ws",
        "content": "",
        "state": "absent",
        "solo": True,
    },
    {"type": "CNAME", "zone": ZONE, "name": "web", "value": "www.example.org"},
    {"type": "MX", "zone": ZONE, "name": "@", "value": "mail.example.org"},
    {"type": "NS", "zone": ZONE, "name": "ws", "value": "ns1.ws.example.org"},
    {"type": "TXT", "zone": ZONE, "name": "@", "value": '"v=spf1 -all"'},
    {
        "type": "SRV",
        "zone": ZONE,
        "name": ZONE,
        "service": "_imaps",
        "proto": "_tcp",
        "priority": 0,
        "weight": 1,
        "port": 993,
        "value": "mail.example.org",
    },
    {"type": "DS", "zone": ZONE, "name": "ws", **DS, "solo": True},
    {
        "type": "NS",
        "zone": ZONE,
        "name": "ws",
        "value": "ns2.ws.example.org",
        "state": "absent",
    },
    {"type": "DS", "zone": ZONE, "name": "ws", **DS, "state": "absent"},
]


def dropped(tasks, records):
    """Args:
        tasks: the tasks of ``tasks/apply.yml``.
        records: the pending ``cloudflare_records`` entries.

    Returns:
        The type of every record no task applies or two tasks apply.
    """
    counts = [
        sum(item == record for item, _, _ in applying_tasks(tasks, records))
        for record in records
    ]
    return [r["type"] for r, count in zip(records, counts, strict=True) if count != 1]


def unjudged(apply, attempt):
    """Args:
        apply: the tasks of ``tasks/apply.yml``.
        attempt: the tasks of ``tasks/attempt.yml``.

    Returns:
        Every register of an apply task whose jobs the attempt never judges.
    """
    judged = json.dumps(attempt)
    registers = sorted(task["register"] for task in apply if MODULE in task)
    return [r for r in registers if f"{r}.results" not in judged]


def old_apply():
    """Returns:
    ``tasks/apply.yml`` as it stood before NS and DS: no DS task, and the
    CNAME task without NS.
    """
    tasks = copy.deepcopy(role_tasks("apply.yml"))
    for task in tasks:
        if MODULE in task and "'NS'" in task["loop"]:
            task["loop"] = task["loop"].replace(",'NS'", "")
    return [t for t in tasks if "'DS'" not in t.get("loop", "")]


class TestApplyTypes(unittest.TestCase):
    def test_every_judged_type_present_or_absent_is_applied_once(self):
        self.assertEqual({r["type"] for r in RECORDS}, set(JUDGED_TYPES))
        self.assertEqual(dropped(role_tasks("apply.yml"), RECORDS), [])

    def test_negative_control_the_old_apply_drops_ns_and_ds(self):
        self.assertEqual(dropped(old_apply(), RECORDS), ["NS", "DS", "NS", "DS"])

    def test_each_record_reaches_the_module_with_its_own_type_and_fields(self):
        for item, name, arguments in applying_tasks(role_tasks("apply.yml"), RECORDS):
            with self.subTest(task=name, type=item["type"], state=item.get("state")):
                self.assertEqual(arguments["type"], item["type"])
                if "state" in item:
                    self.assertEqual(arguments["state"], item["state"])
                if item["type"] == "DS":
                    self.assertEqual(
                        {field: arguments[field] for field in DS},
                        {field: item[field] for field in DS},
                    )
                if item["type"] == "NS":
                    self.assertEqual(arguments["value"], item["value"])
                    self.assertEqual(arguments["priority"], OMIT)

    def test_every_applied_record_passes_the_argument_checks_of_the_module(self):
        for item, name, arguments in applying_tasks(role_tasks("apply.yml"), RECORDS):
            with self.subTest(task=name, type=item["type"], state=item.get("state")):
                self.assertEqual(module_rejections(arguments), [])

    def test_negative_control_solo_on_an_absent_record_fails_the_module(self):
        rejected = [
            (item["type"], item["state"])
            for item, _, arguments in applying_tasks(solo_for_every_state(), RECORDS)
            if SOLO_ABSENT in module_rejections(arguments)
        ]
        self.assertEqual(rejected, [("AAAA", "absent")])

    def test_every_apply_job_is_judged(self):
        self.assertEqual(
            unjudged(role_tasks("apply.yml"), role_tasks("attempt.yml")), []
        )

    def test_negative_control_an_unjudged_ds_job_is_found(self):
        attempt = json.loads(
            json.dumps(role_tasks("attempt.yml")).replace(" + _cf_ds.results", "")
        )
        self.assertEqual(unjudged(role_tasks("apply.yml"), attempt), ["_cf_ds"])


if __name__ == "__main__":
    unittest.main()
