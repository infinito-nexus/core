import ast
import configparser
import json
import re
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from ansible.errors import AnsibleActionFail
from ansible.module_utils.urls import ConnectionError as UrlsConnectionError

from plugins.action import cloudflare_records_converged as plugin
from plugins.action.cloudflare_records_converged import ActionModule
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.install.collections import declared_pins
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-dns-cloudflare-records"
TOKEN = "cf-secret-token-value"
ZONE = "example.org"
ZONE_ID = "zone-id-1"


def rr(rtype, name, content=None, **extra):
    record = {
        "id": f"{rtype}-{name}-{content}",
        "type": rtype,
        "name": name,
        "ttl": 1,
        "comment": None,
        "tags": [],
    }
    if content is not None:
        record["content"] = content
    if rtype in ("A", "AAAA", "CNAME"):
        record["proxied"] = False
    record.update(extra)
    return record


class _Answer:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()


class _FakeCloudflare:
    def __init__(self, pages, zones=None, error=None):
        self.pages = pages
        self.zones = [{"id": ZONE_ID, "name": ZONE}] if zones is None else zones
        self.error = error
        self.calls = []

    def __call__(self, url, method, headers, timeout):
        self.calls.append(
            {"url": url, "method": method, "headers": headers, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if parts.path.endswith("/zones"):
            return _Answer(
                {
                    "success": True,
                    "result": [z for z in self.zones if z["name"] == query["name"][0]],
                }
            )
        page = int(query["page"][0])
        return _Answer(
            {
                "success": True,
                "result": self.pages[page - 1],
                "result_info": {"page": page, "total_pages": len(self.pages)},
            }
        )


def run_split(records, cloudflare):
    with patch.object(plugin, "open_url", side_effect=cloudflare):
        return plugin.split(records, TOKEN, 20)


def a(name, content="203.0.113.7", **extra):
    return {"type": "A", "zone": ZONE, "name": name, "content": content, **extra}


def cname(name, target):
    return {"type": "CNAME", "zone": ZONE, "name": name, "value": target}


def srv(service, port, **extra):
    return {
        "type": "SRV",
        "zone": ZONE,
        "name": ZONE,
        "service": service,
        "proto": "_tcp",
        "priority": 20,
        "weight": 1,
        "port": port,
        "value": "Mail.Example.org.",
        **extra,
    }


def srv_rr(service, port, priority=20, target="mail.example.org", **extra):
    return rr(
        "SRV",
        f"{service}._tcp.{ZONE}",
        priority=priority,
        data={"target": target, "port": port, "weight": 1, "priority": priority},
        **extra,
    )


class TestCloudflareRecordsConverged(unittest.TestCase):
    def test_converged_records_cost_one_zone_read_whatever_their_number(self):
        records = [a(f"*.app{i}") for i in range(20)] + [
            {"type": "AAAA", "zone": ZONE, "name": "*", "content": "2001:DB8::7"}
        ]
        zone = [rr("A", f"*.app{i}.{ZONE}", "203.0.113.7") for i in range(20)]
        zone.append(rr("AAAA", f"*.{ZONE}", "2001:db8::7"))
        cloudflare = _FakeCloudflare([zone])

        pending, labels, warnings = run_split(records, cloudflare)

        self.assertEqual(pending, [])
        self.assertEqual(len(labels), 21)
        self.assertEqual(warnings, [])
        self.assertEqual(len(cloudflare.calls), 2)
        self.assertTrue(all(c["method"] == "GET" for c in cloudflare.calls))
        self.assertTrue(all(c["timeout"] == 20 for c in cloudflare.calls))
        self.assertTrue(all(TOKEN not in c["url"] for c in cloudflare.calls))
        self.assertEqual(
            cloudflare.calls[0]["headers"]["Authorization"], f"Bearer {TOKEN}"
        )

    def test_every_drift_the_module_would_write_keeps_the_record_pending(self):
        drifts = {
            "missing": [],
            "other content": [rr("A", f"www.{ZONE}", "203.0.113.8")],
            "ttl": [rr("A", f"www.{ZONE}", "203.0.113.7", ttl=300)],
            "proxied": [rr("A", f"www.{ZONE}", "203.0.113.7", proxied=True)],
            "proxied unknown": [
                {
                    k: v
                    for k, v in rr("A", f"www.{ZONE}", "203.0.113.7").items()
                    if k != "proxied"
                }
            ],
            "comment": [rr("A", f"www.{ZONE}", "203.0.113.7", comment="hand made")],
            "comment unknown": [
                {
                    k: v
                    for k, v in rr("A", f"www.{ZONE}", "203.0.113.7").items()
                    if k != "comment"
                }
            ],
            "tags": [rr("A", f"www.{ZONE}", "203.0.113.7", tags=["team:ops"])],
            "priority": [rr("A", f"www.{ZONE}", "203.0.113.7", priority=5)],
            "duplicate": [
                rr("A", f"www.{ZONE}", "203.0.113.7"),
                rr("A", f"www.{ZONE}", "203.0.113.7", id="second"),
            ],
        }
        for drift, zone in drifts.items():
            with self.subTest(drift=drift):
                record = a("www")
                pending, labels, _ = run_split([record], _FakeCloudflare([zone]))
                self.assertEqual(pending, [record])
                self.assertEqual(labels, [])

    def test_a_record_matches_the_declared_proxied_and_ttl(self):
        record = a("www", proxied=True, ttl="1")
        zone = [rr("A", f"www.{ZONE}", "203.0.113.7", proxied=True)]

        pending, labels, _ = run_split([record], _FakeCloudflare([zone]))

        self.assertEqual(pending, [])
        self.assertEqual(labels, [f"A www.{ZONE}"])

    def test_solo_record_stays_pending_while_another_record_shares_its_name(self):
        record = a("mail", solo=True)
        alone = [rr("A", f"mail.{ZONE}", "203.0.113.7")]
        crowded = [*alone, rr("A", f"mail.{ZONE}", "198.51.100.1")]

        self.assertEqual(run_split([record], _FakeCloudflare([alone]))[0], [])
        self.assertEqual(run_split([record], _FakeCloudflare([crowded]))[0], [record])
        self.assertEqual(run_split([a("mail")], _FakeCloudflare([crowded]))[0], [])

    def test_cname_is_normalized_like_the_module_and_compared_by_target(self):
        record = {
            "type": "CNAME",
            "zone": ZONE,
            "name": "autoconfig",
            "value": "Mail.Example.org.",
            "proxied": True,
        }
        held = [rr("CNAME", f"autoconfig.{ZONE}", "mail.example.org")]
        moved = [rr("CNAME", f"autoconfig.{ZONE}", "other.example.org")]
        proxied = [rr("CNAME", f"autoconfig.{ZONE}", "mail.example.org", proxied=True)]

        self.assertEqual(run_split([record], _FakeCloudflare([held]))[0], [])
        self.assertEqual(run_split([record], _FakeCloudflare([moved]))[0], [record])
        self.assertEqual(run_split([record], _FakeCloudflare([proxied]))[0], [record])

    def test_mx_priority_defaults_like_apply_and_is_compared(self):
        record = {"type": "MX", "zone": ZONE, "name": "@", "value": "mail.example.org"}
        held = [rr("MX", ZONE, "mail.example.org", priority=10)]
        other = [rr("MX", ZONE, "mail.example.org", priority=20)]

        self.assertEqual(run_split([record], _FakeCloudflare([held]))[0], [])
        self.assertEqual(run_split([record], _FakeCloudflare([other]))[0], [record])
        self.assertEqual(
            run_split([dict(record, priority=20)], _FakeCloudflare([other]))[0], []
        )

    def test_txt_content_is_compared_exactly(self):
        record = {
            "type": "TXT",
            "zone": ZONE,
            "name": "_dmarc",
            "value": '"v=DMARC1; p=reject"',
            "solo": True,
        }
        held = [rr("TXT", f"_dmarc.{ZONE}", '"v=DMARC1; p=reject"')]
        unquoted = [rr("TXT", f"_dmarc.{ZONE}", "v=DMARC1; p=reject")]
        recased = [rr("TXT", f"_dmarc.{ZONE}", '"V=DMARC1; p=reject"')]

        self.assertEqual(run_split([record], _FakeCloudflare([held]))[0], [])
        self.assertEqual(run_split([record], _FakeCloudflare([unquoted]))[0], [record])
        self.assertEqual(run_split([record], _FakeCloudflare([recased]))[0], [record])

    def test_srv_is_matched_by_weight_port_target_and_compared_by_data(self):
        record = srv("submission", 587, solo=True)
        cases = {
            "held": ([srv_rr("_submission", 587)], []),
            "priority": ([srv_rr("_submission", 587, priority=10)], [record]),
            "port": ([srv_rr("_submission", 465)], [record]),
            "ambiguous": (
                [
                    srv_rr("_submission", 587),
                    srv_rr("_submission", 587, priority=30, id="b"),
                ],
                [record],
            ),
            "stale data keys": (
                [
                    dict(
                        srv_rr("_submission", 587),
                        data={
                            "target": "mail.example.org",
                            "port": 587,
                            "weight": 1,
                            "priority": 20,
                            "service": "_submission",
                        },
                    )
                ],
                [record],
            ),
        }
        for case, (zone, want) in cases.items():
            with self.subTest(case=case):
                self.assertEqual(run_split([record], _FakeCloudflare([zone]))[0], want)

    def test_records_outside_the_judged_shapes_stay_pending_without_a_read(self):
        records = [
            a("gone", state="absent"),
            {"type": "CAA", "zone": ZONE, "name": "@", "value": "letsencrypt.org"},
            {"type": "A", "zone": ZONE, "name": "www"},
            a("www", ttl=None),
            a("www", proxied="perhaps"),
            {k: v for k, v in srv("imaps", 993).items() if k != "port"},
            "not a record",
        ]
        cloudflare = _FakeCloudflare([[]])

        pending, labels, warnings = run_split(records, cloudflare)

        self.assertEqual(pending, records)
        self.assertEqual(labels, [])
        self.assertEqual(warnings, [])
        self.assertEqual(cloudflare.calls, [])

    def test_an_unreadable_zone_leaves_its_records_to_the_module_and_warns_without_the_token(
        self,
    ):
        records = [a("www"), a("api")]
        error = HTTPError(
            f"{plugin.API}/zones?name={ZONE}", 429, "Too Many Requests", {}, None
        )
        cloudflare = _FakeCloudflare([[]], error=error)

        pending, labels, warnings = run_split(records, cloudflare)

        self.assertEqual(pending, records)
        self.assertEqual(labels, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn(ZONE, warnings[0])
        self.assertIn("429", warnings[0])
        self.assertNotIn(TOKEN, warnings[0])
        self.assertEqual(len(cloudflare.calls), 1)

    def test_every_transport_failure_leaves_the_records_to_the_module(self):
        for error in (
            IncompleteRead(b""),
            TimeoutError("timed out"),
            URLError("refused"),
            UrlsConnectionError("tls"),
        ):
            with self.subTest(error=type(error).__name__):
                record = a("www")
                pending, _, warnings = run_split(
                    [record], _FakeCloudflare([[]], error=error)
                )
                self.assertEqual(pending, [record])
                self.assertEqual(len(warnings), 1)

    def test_a_zone_name_without_exactly_one_zone_leaves_its_records_to_the_module(
        self,
    ):
        record = a("www")
        pending, _, warnings = run_split([record], _FakeCloudflare([[]], zones=[]))

        self.assertEqual(pending, [record])
        self.assertIn("0 Cloudflare zones match example.org", warnings[0])

    def test_an_answer_without_success_leaves_its_records_to_the_module(self):
        record = a("www")
        with patch.object(
            plugin,
            "open_url",
            side_effect=lambda *args, **kwargs: _Answer(
                {"success": False, "errors": [{"code": 10000}]}
            ),
        ):
            pending, _, warnings = plugin.split([record], TOKEN, 20)

        self.assertEqual(pending, [record])
        self.assertIn("10000", warnings[0])
        self.assertNotIn(TOKEN, warnings[0])

    def test_every_page_of_the_zone_is_read(self):
        record = a("late")
        pages = [
            [rr("A", f"early{i}.{ZONE}", "203.0.113.7") for i in range(3)],
            [rr("A", f"late.{ZONE}", "203.0.113.7")],
        ]
        cloudflare = _FakeCloudflare(pages)

        pending, labels, _ = run_split([record], cloudflare)

        self.assertEqual(pending, [])
        self.assertEqual(labels, [f"A late.{ZONE}"])
        self.assertEqual(len(cloudflare.calls), 3)

    def test_each_zone_is_read_once_and_order_is_kept(self):
        other = {
            "type": "A",
            "zone": "Other.NET",
            "name": "www",
            "content": "203.0.113.7",
        }
        records = [a("one"), other, a("two")]
        zones = [
            {"id": ZONE_ID, "name": ZONE},
            {"id": "zone-id-2", "name": "other.net"},
        ]
        cloudflare = _FakeCloudflare(
            [[rr("A", f"two.{ZONE}", "203.0.113.7")]], zones=zones
        )

        pending, labels, _ = run_split(records, cloudflare)

        self.assertEqual(pending, [records[0], other])
        self.assertEqual(labels, [f"A two.{ZONE}"])
        self.assertEqual(len(cloudflare.calls), 4)

    def test_fields_the_module_rejects_as_int_stay_pending(self):
        held = [rr("A", f"www.{ZONE}", "203.0.113.7")]
        for ttl in (1.5, "1.5", True, "one"):
            with self.subTest(ttl=ttl):
                record = a("www", ttl=ttl)
                pending, labels, _ = run_split([record], _FakeCloudflare([held]))
                self.assertEqual(pending, [record])
                self.assertEqual(labels, [])
        for ttl in (1, "1", 1.0, "1.0"):
            with self.subTest(ttl=ttl):
                record = a("www", ttl=ttl)
                self.assertEqual(run_split([record], _FakeCloudflare([held]))[0], [])
        mx = {"type": "MX", "zone": ZONE, "name": "@", "value": "mail.example.org"}
        mx_held = [rr("MX", ZONE, "mail.example.org", priority=10)]
        for priority in (10.5, False):
            with self.subTest(priority=priority):
                record = dict(mx, priority=priority)
                pending, _, _ = run_split([record], _FakeCloudflare([mx_held]))
                self.assertEqual(pending, [record])
        record = srv("submission", 587.5)
        zone = [srv_rr("_submission", 587)]
        self.assertEqual(run_split([record], _FakeCloudflare([zone]))[0], [record])

    def test_a_name_with_a_solo_entry_and_another_entry_stays_pending(self):
        records = [a("h", "192.0.2.1", solo=True), a("h", "192.0.2.2")]
        both = [rr("A", f"h.{ZONE}", "192.0.2.1"), rr("A", f"h.{ZONE}", "192.0.2.2")]
        for held in (both, both[:1], both[1:]):
            with self.subTest(held=[r["content"] for r in held]):
                pending, labels, _ = run_split(records, _FakeCloudflare([held]))
                self.assertEqual(pending, records)
                self.assertEqual(labels, [])

    def test_a_name_another_entry_deletes_from_stays_pending(self):
        held = [rr("A", f"h.{ZONE}", "192.0.2.1")]
        records = [a("h", "192.0.2.1"), a("h", "192.0.2.1", state="absent")]

        pending, labels, _ = run_split(records, _FakeCloudflare([held]))

        self.assertEqual(pending, records)
        self.assertEqual(labels, [])

    def test_a_hazard_on_one_name_or_type_leaves_the_others_judged(self):
        records = [
            a("h", "192.0.2.1", solo=True),
            a("h", "192.0.2.2"),
            a("other"),
            {"type": "AAAA", "zone": ZONE, "name": "h", "content": "2001:db8::1"},
        ]
        zone = [
            rr("A", f"h.{ZONE}", "192.0.2.1"),
            rr("A", f"other.{ZONE}", "203.0.113.7"),
            rr("AAAA", f"h.{ZONE}", "2001:db8::1"),
        ]

        pending, labels, _ = run_split(records, _FakeCloudflare([zone]))

        self.assertEqual(pending, records[:2])
        self.assertEqual(labels, [f"A other.{ZONE}", f"AAAA h.{ZONE}"])

    def test_one_record_declared_twice_with_different_settings_stays_pending(self):
        x = f"x.{ZONE}"
        mx = {"type": "MX", "zone": ZONE, "name": "x", "value": "mx.example.org"}
        groups = {
            "cname target": (
                [cname("x", "a.example.org"), cname("x", "b.example.org")],
                [rr("CNAME", x, "a.example.org")],
                [rr("CNAME", x, "b.example.org")],
            ),
            "a ttl": (
                [a("x", ttl=1), a("x", ttl=300)],
                [rr("A", x, "203.0.113.7")],
                [rr("A", x, "203.0.113.7", ttl=300)],
            ),
            "mx priority": (
                [mx, dict(mx, value="MX.example.org.", priority=20)],
                [rr("MX", x, "mx.example.org", priority=10)],
                [rr("MX", x, "mx.example.org", priority=20)],
            ),
        }
        for group, (records, *held) in groups.items():
            for zone in held:
                with self.subTest(group=group, held=zone):
                    pending, labels, _ = run_split(records, _FakeCloudflare([zone]))
                    self.assertEqual(pending, records)
                    self.assertEqual(labels, [])

    def test_a_name_with_an_entry_the_plugin_cannot_judge_stays_pending(self):
        t = f"t.{ZONE}"
        txt = {"type": "TXT", "zone": ZONE, "name": "t"}
        groups = {
            "txt int value": (
                [dict(txt, value=12345), dict(txt, value="12345", ttl=300)],
                [rr("TXT", t, "12345", ttl=300)],
            ),
            "txt int value last": (
                [dict(txt, value="12345", ttl=300), dict(txt, value=12345)],
                [rr("TXT", t, "12345", ttl=300)],
            ),
            "a null ttl": (
                [a("x", ttl=None), a("x", ttl=300)],
                [rr("A", f"x.{ZONE}", "203.0.113.7", ttl=300)],
            ),
        }
        for group, (records, zone) in groups.items():
            with self.subTest(group=group):
                pending, labels, _ = run_split(records, _FakeCloudflare([zone]))
                self.assertEqual(pending, records)
                self.assertEqual(labels, [])

    def test_entries_of_one_name_the_module_edits_as_distinct_or_equal_records_stay_judged(
        self,
    ):
        x = f"x.{ZONE}"
        groups = {
            "distinct a": (
                [a("x", "192.0.2.1"), a("x", "192.0.2.2", ttl=300)],
                [rr("A", x, "192.0.2.1"), rr("A", x, "192.0.2.2", ttl=300)],
            ),
            "distinct srv": (
                [srv("submission", 587), srv("submission", 465, priority=10)],
                [
                    srv_rr("_submission", 587),
                    srv_rr("_submission", 465, priority=10, id="b"),
                ],
            ),
            "equal a": (
                [a("x", ttl=1), a("x", ttl="1")],
                [rr("A", x, "203.0.113.7")],
            ),
        }
        for group, (records, zone) in groups.items():
            with self.subTest(group=group):
                pending, labels, _ = run_split(records, _FakeCloudflare([zone]))
                self.assertEqual(pending, [])
                self.assertEqual(len(labels), 2)

    def test_txt_held_both_quoted_and_unquoted_stays_pending(self):
        record = {
            "type": "TXT",
            "zone": ZONE,
            "name": "_dmarc",
            "value": '"v=DMARC1; p=reject"',
        }
        quoted = rr("TXT", f"_dmarc.{ZONE}", '"v=DMARC1; p=reject"')
        unquoted = rr("TXT", f"_dmarc.{ZONE}", "v=dmarc1; p=reject", id="unquoted")
        other = rr("TXT", f"_dmarc.{ZONE}", '"v=spf1 -all"', id="spf")

        self.assertEqual(
            run_split([record], _FakeCloudflare([[quoted, unquoted]]))[0], [record]
        )
        self.assertEqual(run_split([record], _FakeCloudflare([[quoted, other]]))[0], [])


class _FakeTask:
    def __init__(self, args):
        self.args = args


def _action(args):
    action = object.__new__(ActionModule)
    action._task = _FakeTask(args)
    return action


class TestCloudflareRecordsConvergedAction(unittest.TestCase):
    def test_run_returns_pending_and_converged_without_change(self):
        record = a("www")
        cloudflare = _FakeCloudflare([[rr("A", f"www.{ZONE}", "203.0.113.7")]])
        action = _action(
            {"api_token": TOKEN, "records": [record, a("api")], "timeout": "20"}
        )
        with (
            patch(
                "plugins.action.cloudflare_records_converged.ActionBase.run",
                autospec=True,
                return_value={},
            ),
            patch.object(plugin, "open_url", side_effect=cloudflare),
        ):
            result = action.run(task_vars={})

        self.assertFalse(result["changed"])
        self.assertEqual(result["pending"], [a("api")])
        self.assertEqual(result["converged"], [f"A www.{ZONE}"])
        self.assertNotIn("warnings", result)
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_run_rejects_wrong_arguments(self):
        for args in (
            {"records": [], "timeout": 20},
            {"api_token": TOKEN, "records": [], "timeout": 20, "zone": ZONE},
            {"api_token": TOKEN, "records": "a", "timeout": 20},
            {"api_token": TOKEN, "records": [], "timeout": "soon"},
        ):
            with (
                self.subTest(args=sorted(args)),
                patch(
                    "plugins.action.cloudflare_records_converged.ActionBase.run",
                    autospec=True,
                    return_value={},
                ),
                self.assertRaises(AnsibleActionFail),
            ):
                _action(args).run(task_vars={})


def _task(tasks, name):
    return next(t for t in tasks if t.get("name") == name)


class TestApplyDefaultsMatchThePlugin(unittest.TestCase):
    def test_the_defaults_apply_hands_the_module_are_the_ones_the_plugin_predicts(self):
        tasks = load_yaml_any(str(ROLE / "tasks" / "apply.yml"))
        a_args = _task(tasks, "📌 Apply A/AAAA")["community.general.cloudflare_dns"]
        cname_args = _task(tasks, "📌 Apply CNAME/MX/TXT")[
            "community.general.cloudflare_dns"
        ]
        srv_args = _task(tasks, "📌 Apply SRV")["community.general.cloudflare_dns"]

        def default(text, field):
            match = re.search(rf"item\.{field} \| default\(([^)]*)\)", text)
            self.assertIsNotNone(match, f"{field} default not found in {text!r}")
            return load_yaml_str(match.group(1))

        for args in (a_args, cname_args, srv_args):
            self.assertEqual(default(args["ttl"], "ttl"), plugin.APPLY_TTL)
            self.assertEqual(default(args["state"], "state"), plugin.APPLY_STATE)
            self.assertEqual(default(args["solo"], "solo"), plugin.APPLY_SOLO)
        self.assertEqual(default(a_args["proxied"], "proxied"), plugin.APPLY_PROXIED)
        self.assertEqual(
            default(cname_args["priority"], "priority"), plugin.APPLY_MX_PRIORITY
        )
        self.assertIn("omit", cname_args["priority"])
        self.assertNotIn("priority", a_args)
        self.assertNotIn("proxied", cname_args)
        self.assertNotIn("proxied", srv_args)
        self.assertEqual(srv_args["priority"], "{{ item.priority }}")
        self.assertEqual(a_args["content"], "{{ item.content }}")
        self.assertEqual(cname_args["value"], "{{ item.value }}")
        self.assertEqual(srv_args["value"], "{{ item.value }}")

    def test_the_first_attempt_queues_only_what_the_plugin_left_pending(self):
        tasks = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))
        names = [t.get("name") for t in tasks]
        check = next(t for t in tasks if "cloudflare_records_converged" in t)
        queue = next(
            t for t in tasks if "_cf_pending" in t.get("ansible.builtin.set_fact", {})
        )

        self.assertEqual(
            check["cloudflare_records_converged"]["records"], "{{ cloudflare_records }}"
        )
        self.assertEqual(check["register"], "_cf_converged")
        self.assertIn("cloudflare_no_log", check["no_log"])
        self.assertEqual(
            queue["ansible.builtin.set_fact"]["_cf_pending"],
            "{{ _cf_converged.pending }}",
        )
        self.assertLess(names.index(check["name"]), names.index(queue["name"]))


def _resolved_community_general() -> Path:
    """
    Returns:
        The community.general directory of the first ``collections_paths``
        entry of the repository's ansible.cfg that holds one, as Ansible
        resolves it.
    """
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(PROJECT_ROOT / "ansible.cfg", encoding="utf-8")
    for entry in config.get("defaults", "collections_paths").split(":"):
        base = Path(entry).expanduser()
        if not base.is_absolute():
            base = PROJECT_ROOT / base
        candidate = base / "ansible_collections" / "community" / "general"
        if (candidate / "plugins" / "modules" / "cloudflare_dns.py").is_file():
            return candidate
    raise AssertionError("no collections_paths entry holds community.general")


def _argument_spec_defaults(module: Path) -> dict:
    """
    Args:
        module: path of an Ansible module source file.

    Returns:
        ``{option: default}`` for every option of the module's
        ``argument_spec`` that declares a literal default.
    """
    tree = ast.parse(read_text(str(module)))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "argument_spec":
            defaults = {}
            for option in node.value.keywords:
                fields = {k.arg: k.value for k in option.value.keywords}
                if "default" in fields:
                    defaults[option.arg] = ast.literal_eval(fields["default"])
            return defaults
    raise AssertionError(f"no argument_spec in {module}")


class TestModuleDefaultsMatchThePlugin(unittest.TestCase):
    def test_the_module_defaults_the_plugin_predicts_match_the_resolved_collection(
        self,
    ):
        collection = _resolved_community_general()
        manifest = json.loads(read_text(str(collection / "MANIFEST.json")))
        defaults = _argument_spec_defaults(
            collection / "plugins" / "modules" / "cloudflare_dns.py"
        )

        self.assertEqual(
            manifest["collection_info"]["version"], plugin.REVIEWED_COMMUNITY_GENERAL
        )
        self.assertEqual(defaults["priority"], plugin.MODULE_PRIORITY)
        self.assertEqual(defaults["proxied"], plugin.MODULE_PROXIED)

    def test_a_new_community_general_pin_forces_a_review_of_the_plugin(self):
        pins = dict(
            declared_pins(PROJECT_ROOT / "requirements" / "requirements.galaxy.yml")
        )

        self.assertEqual(pins["community.general"], plugin.REVIEWED_COMMUNITY_GENERAL)


if __name__ == "__main__":
    unittest.main()
