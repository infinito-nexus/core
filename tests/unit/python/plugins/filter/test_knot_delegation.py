from __future__ import annotations

import copy
import json
import re
import unittest

import jinja2
from ansible.errors import AnsibleFilterError

from plugins.action.cloudflare_records_converged import converged, expected
from plugins.filter import knot_delegation as delegation
from plugins.filter.domain_tools import to_zone
from tests.utils.cloudflare_apply import (
    applying_tasks,
    module_rejections,
    role_tasks,
    solo_for_every_state,
)
from tests.utils.knot_keys import (
    ALGORITHM,
    FIRST_KSK,
    HOSTS,
    HOUR,
    NEW_ZONE_KSK,
    NOW,
    OLD_KSK,
    OWNER,
    PARENT,
    ROLLED_KSK,
    SECOND_KSK,
    ZONE,
    ZSK,
    active,
    addresses,
    build,
    cloudflare_zones,
    digest,
    ds_output,
    ds_record,
)
from utils.cache.files import PROJECT_ROOT, read_text

KNOT_DIR = PROJECT_ROOT / "roles" / "svc-dns-knot" / "templates"
ZONE_TEMPLATE = read_text(str(KNOT_DIR / "zone.j2"))
KNOT_CONF = read_text(str(KNOT_DIR / "knot.conf.j2"))
LISTEN = re.compile(r"^\s*listen:\s*\[([^\]]*)\]", re.MULTILINE)
STAGING = "staging.example.org"
STAGING_ZONE = f"ws.{STAGING}"
CO_UK = "example.co.uk"
CO_UK_ZONE = f"ws.{CO_UK}"
NO_READY_KEY = "error: (no key ready for submission)"


def answers(zone, zones):
    return {
        candidate: cloudflare_zones(candidate, zones)
        for candidate in delegation.knot_parent_candidates(zone)
    }


def zone_file(template, ip4s):
    """Args:
        template: the text of ``templates/zone.j2`` of ``svc-dns-knot``.
        ip4s: ``KNOT_ADDRESSES``, the primary first.

    Returns:
        ``(targets, a, aaaa)``: the absolute NS targets, and ``{target:
        address}`` of the A and the AAAA records of the zone file.
    """
    environment = jinja2.Environment(
        trim_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    text = environment.from_string(template).render(
        KNOT_ZONE=ZONE, KNOT_ADDRESSES=list(ip4s), application_id="svc-dns-knot"
    )
    targets, a, aaaa = [], {}, {}
    for fields in (line.split() for line in text.splitlines()):
        if fields[1:2] == ["NS"]:
            targets.append(f"{fields[2]}.{ZONE}")
        elif fields[1:2] == ["A"]:
            a[f"{fields[0]}.{ZONE}"] = fields[2]
        elif fields[1:2] == ["AAAA"]:
            aaaa[f"{fields[0]}.{ZONE}"] = fields[2]
    return targets, a, aaaa


def listens_on_ipv6(conf):
    """Args:
        conf: the text of ``templates/knot.conf.j2`` of ``svc-dns-knot``.

    Returns:
        Whether an address the server listens on is an IPv6 address.
    """
    (listen,) = LISTEN.findall(conf)
    return any(":" in entry.strip().split("@")[0] for entry in listen.split(","))


def delegation_findings(records, ip4s, template, conf):
    """Args:
        records: the ``cloudflare_records`` entries of a delegation.
        ip4s: the IPv4 addresses of the knot group, the primary first.
        template: the text of ``templates/zone.j2``.
        conf: the text of ``templates/knot.conf.j2``.

    Returns:
        One message per gap: NS targets or glue A other than the zone file's,
        an AAAA in the glue or the zone file while knot listens on IPv4 only,
        a record outside the parent zone, and not exactly one DS of the
        subzone.
    """
    findings = []
    targets, zone_a, zone_aaaa = zone_file(template, ip4s)
    ns = [r["value"] for r in records if r["type"] == "NS" and r["name"] == ZONE]
    if ns != targets:
        findings.append(f"NS {ns} differ from the zone file {targets}")
    a = {r["name"]: r["content"] for r in records if r["type"] == "A"}
    if a != zone_a:
        findings.append(f"glue A {a} differs from the zone file {zone_a}")
    aaaa = sorted(r["name"] for r in records if r["type"] == "AAAA")
    if not listens_on_ipv6(conf) and (aaaa or zone_aaaa):
        findings.append(
            f"AAAA glue {aaaa} and zone file AAAA {sorted(zone_aaaa)} while knot "
            f"listens on IPv4 only"
        )
    outside = sorted({r["zone"] for r in records} - {PARENT})
    if outside:
        findings.append(f"records outside {PARENT}: {outside}")
    if [r["name"] for r in records if r["type"] == "DS"] != [ZONE]:
        findings.append("not exactly one DS of the subzone")
    return findings


def module_findings(records):
    """Args:
        records: the ``cloudflare_records`` entries of a delegation.

    Returns:
        Every argument check of ``community.general.cloudflare_dns`` a record
        fails, rendered through ``tasks/apply.yml`` of
        ``sys-dns-cloudflare-records`` with its solo guard and without it.
    """
    variants = {
        "apply": role_tasks("apply.yml"),
        "unguarded": solo_for_every_state(),
    }
    return [
        f"{variant}: {item['type']} {item['name']}: {message}"
        for variant, tasks in variants.items()
        for item, _, arguments in applying_tasks(tasks, records)
        for message in module_rejections(arguments)
    ]


def cloudflare_rr(record):
    """Args:
        record: a present entry of the delegation.

    Returns:
        The record as the Cloudflare API returns it once it stands, a DS
        with its digest in lowercase.
    """
    rr = {
        "id": f"{record['type']}-{record['name']}",
        "type": record["type"],
        "name": record["name"],
        "ttl": 1,
        "proxied": False,
        "comment": None,
        "tags": [],
    }
    if record["type"] == "DS":
        data = {
            "key_tag": record["key_tag"],
            "algorithm": record["algorithm"],
            "digest_type": record["hash_type"],
            "digest": record["value"].lower(),
        }
        return {**rr, "data": data, "content": " ".join(map(str, data.values()))}
    content = record["content"] if record["type"] == "A" else record["value"]
    return {**rr, "content": content}


def knotc(rc, stdout, stderr):
    return {"rc": rc, "stdout": stdout, "stderr": stderr}


class TestKnotKsk(unittest.TestCase):
    def test_a_new_zone_waits_for_the_submission_of_its_only_ksk(self):
        ksk = delegation.knot_ksk(OWNER, json.dumps([ZSK, NEW_ZONE_KSK]), NOW)
        self.assertEqual(
            ksk, {"tag": FIRST_KSK, "algorithm": ALGORITHM, "submitted": False}
        )

    def test_an_active_ksk_is_submitted(self):
        ksk = delegation.knot_ksk(ZONE, [ZSK, OLD_KSK], NOW)
        self.assertEqual(ksk["tag"], FIRST_KSK)
        self.assertTrue(ksk["submitted"])

    def test_a_rollover_picks_the_new_ksk_until_it_is_submitted(self):
        ksk = delegation.knot_ksk(ZONE, [ZSK, OLD_KSK, ROLLED_KSK], NOW)
        self.assertEqual((ksk["tag"], ksk["submitted"]), (SECOND_KSK, False))

    def test_a_ksk_not_yet_ready_keeps_the_active_ksk(self):
        published = {**ROLLED_KSK, "ready": NOW + HOUR}
        ksk = delegation.knot_ksk(ZONE, [ZSK, OLD_KSK, published], NOW)
        self.assertEqual((ksk["tag"], ksk["submitted"]), (FIRST_KSK, True))

    def test_a_retiring_ksk_is_never_current(self):
        retiring = {**OLD_KSK, "retire-active": NOW - 60}
        active_ksk = {**ROLLED_KSK, "active": NOW - 60}
        ksk = delegation.knot_ksk(ZONE, [ZSK, retiring, active_ksk], NOW)
        self.assertEqual((ksk["tag"], ksk["submitted"]), (SECOND_KSK, True))
        with self.assertRaisesRegex(AnsibleFilterError, "no ready, unretired KSK"):
            delegation.knot_ksk(ZONE, [ZSK, retiring], NOW)

    def test_negative_control_timers_of_another_format_fail(self):
        human = {**NEW_ZONE_KSK, "ready": "-1h"}
        with self.assertRaisesRegex(AnsibleFilterError, "no integer 'ready'"):
            delegation.knot_ksk(ZONE, [ZSK, human], NOW)


class TestKnotDs(unittest.TestCase):
    def setUp(self):
        self.ksk = delegation.knot_ksk(ZONE, [ZSK, NEW_ZONE_KSK], NOW)

    def test_the_ds_is_the_sha256_ds_of_the_current_ksk(self):
        record = delegation.knot_ds(
            OWNER, self.ksk, ds_output(OWNER, FIRST_KSK, SECOND_KSK)
        )
        self.assertEqual(
            record,
            {
                "key_tag": FIRST_KSK,
                "algorithm": ALGORITHM,
                "hash_type": 2,
                "value": digest(FIRST_KSK, 2).upper(),
            },
        )

    def test_negative_control_a_ds_of_another_key_fails(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, rf"current KSK {FIRST_KSK}.*\[{SECOND_KSK}\]"
        ):
            delegation.knot_ds(ZONE, self.ksk, ds_output(OWNER, SECOND_KSK))

    def test_negative_control_a_ds_without_sha256_fails(self):
        sha384 = "".join(
            line
            for line in ds_output(OWNER, FIRST_KSK).splitlines(keepends=True)
            if f" {ALGORITHM} 4 " in line
        )
        with self.assertRaisesRegex(AnsibleFilterError, "names 0 SHA-256 DS"):
            delegation.knot_ds(ZONE, self.ksk, sha384)

    def test_negative_control_a_ds_of_another_zone_fails(self):
        with self.assertRaisesRegex(AnsibleFilterError, "a DS of other.example.org"):
            delegation.knot_ds(
                ZONE, self.ksk, ds_output("other.example.org.", FIRST_KSK)
            )


class TestKnotParentZone(unittest.TestCase):
    def test_the_candidates_are_the_proper_suffixes_longest_first(self):
        self.assertEqual(
            delegation.knot_parent_candidates(CO_UK_ZONE), [CO_UK, "co.uk"]
        )
        self.assertEqual(
            delegation.knot_parent_candidates(f"{STAGING_ZONE}."), [STAGING, PARENT]
        )

    def test_the_parent_is_the_longest_active_cloudflare_zone_above_the_subzone(self):
        cases = {
            ZONE: (active(PARENT, "example.net"), PARENT),
            STAGING_ZONE: (active(PARENT, STAGING), STAGING),
            CO_UK_ZONE: (active(CO_UK), CO_UK),
        }
        for zone, (zones, parent) in cases.items():
            with self.subTest(zone=zone):
                self.assertEqual(
                    delegation.knot_parent_zone(zone, answers(zone, zones)), parent
                )

    def test_negative_control_the_last_two_labels_miss_the_parent(self):
        self.assertEqual(to_zone(CO_UK_ZONE), "co.uk")
        self.assertEqual(to_zone(STAGING_ZONE), PARENT)

    def test_a_name_with_only_a_pending_or_moved_zone_is_no_parent(self):
        for status in ("pending", "moved"):
            with self.subTest(status=status):
                found = answers(STAGING_ZONE, ((STAGING, status), *active(PARENT)))
                self.assertEqual(
                    delegation.knot_parent_zone(STAGING_ZONE, found), PARENT
                )

    def test_negative_control_the_same_zone_active_is_the_parent(self):
        found = answers(STAGING_ZONE, active(STAGING, PARENT))
        self.assertEqual(delegation.knot_parent_zone(STAGING_ZONE, found), STAGING)

    def test_a_missing_or_ambiguous_parent_fails(self):
        cases = {
            "reads no active zone": answers(STAGING_ZONE, active("example.net")),
            "no active zone of": answers(
                STAGING_ZONE, ((STAGING, "pending"), (PARENT, "moved"))
            ),
            "is ambiguous": answers(STAGING_ZONE, active(STAGING, STAGING, PARENT)),
            r"\['active', 'moved'\].*ambiguous": answers(
                STAGING_ZONE, ((STAGING, "moved"), *active(STAGING, PARENT))
            ),
            f"no Cloudflare answer for {STAGING}": {PARENT: active(PARENT)},
        }
        for message, found in cases.items():
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(AnsibleFilterError, message),
            ):
                delegation.knot_parent_zone(STAGING_ZONE, found)


class TestKnotDelegation(unittest.TestCase):
    def test_every_knot_host_gets_its_ns_and_glue_as_in_the_zone_file(self):
        records = build(HOSTS)
        ip4s = addresses(HOSTS).values()
        self.assertEqual(
            delegation_findings(records, ip4s, ZONE_TEMPLATE, KNOT_CONF), []
        )
        self.assertEqual(
            [r["type"] for r in records], ["NS", "A"] * len(HOSTS) + ["DS"]
        )
        (ds,) = (r for r in records if r["type"] == "DS")
        self.assertEqual(
            ds,
            {
                "zone": PARENT,
                "type": "DS",
                "name": ZONE,
                "key_tag": FIRST_KSK,
                "algorithm": ALGORITHM,
                "hash_type": 2,
                "value": digest(FIRST_KSK, 2).upper(),
                "solo": True,
            },
        )

    def test_knot_listens_on_ipv4_only(self):
        self.assertFalse(listens_on_ipv6(KNOT_CONF))
        planted = KNOT_CONF.replace("0.0.0.0@53", "0.0.0.0@53, ::@53")
        self.assertNotEqual(planted, KNOT_CONF)
        self.assertTrue(listens_on_ipv6(planted))

    def test_negative_control_the_r3_aaaa_glue_and_zone_file_are_found(self):
        ip4s = addresses(HOSTS).values()
        r3_glue = {
            "zone": PARENT,
            "type": "AAAA",
            "name": f"ns1.{ZONE}",
            "content": HOSTS["knot-primary"]["ip6"],
            "proxied": False,
            "state": "present",
            "solo": True,
        }
        r3_zone = ZONE_TEMPLATE.replace(
            "{% endfor %}", "ns{{ loop.index }} AAAA 2001:db8::1\n{% endfor %}"
        )
        self.assertNotEqual(r3_zone, ZONE_TEMPLATE)
        plants = {
            "glue": ([*build(HOSTS), r3_glue], ZONE_TEMPLATE),
            "zone file": (build(HOSTS), r3_zone),
        }
        for case, (records, template) in plants.items():
            with self.subTest(case=case):
                findings = delegation_findings(records, ip4s, template, KNOT_CONF)
                self.assertIn("listens on IPv4 only", " ".join(findings))

    def test_every_record_passes_the_argument_checks_of_cloudflare_dns(self):
        self.assertEqual(module_findings(build(HOSTS)), [])

    def test_negative_control_a_secondary_without_an_address_fails(self):
        for address in ("", "127.0.0.1", "2001:db8::2"):
            with self.subTest(address=address):
                hosts = copy.deepcopy(HOSTS)
                hosts["knot-secondary-b"]["ip4"] = address
                with self.assertRaisesRegex(AnsibleFilterError, "knot-secondary-b"):
                    build(hosts)

    def test_the_zone_file_keeps_a_loopback_address_the_glue_refuses(self):
        _, zone_a, _ = zone_file(ZONE_TEMPLATE, ["127.0.0.1"])
        self.assertEqual(zone_a, {f"ns1.{ZONE}": "127.0.0.1"})

    def test_negative_control_a_dropped_secondary_glue_is_found(self):
        records = [
            r
            for r in build(HOSTS)
            if not (r["type"] == "A" and r["name"] == f"ns3.{ZONE}")
        ]
        findings = delegation_findings(
            records, addresses(HOSTS).values(), ZONE_TEMPLATE, KNOT_CONF
        )
        self.assertIn("glue A", " ".join(findings))

    def test_a_subzone_outside_its_parent_fails(self):
        with self.assertRaisesRegex(AnsibleFilterError, "is not below"):
            delegation.knot_delegation(
                ZONE, "example.net", addresses(HOSTS), ds_record()
            )

    def test_a_second_deploy_finds_every_record_converged(self):
        records = build(HOSTS)
        zone = [cloudflare_rr(r) for r in records]
        drifted = [dict(rr, ttl=300) for rr in zone]
        for record in records:
            with self.subTest(name=record["name"], type=record["type"]):
                want = expected(record)
                self.assertIsNotNone(want)
                self.assertTrue(converged(want, zone))
                self.assertFalse(converged(want, drifted))


class TestKnotSubmission(unittest.TestCase):
    def test_knotc_outcomes(self):
        cases = {
            "confirmed": knotc(0, "OK", ""),
            "unready": knotc(1, "", NO_READY_KEY),
            "failed": knotc(1, "", "error: (operation not permitted)"),
        }
        for outcome, result in cases.items():
            with self.subTest(outcome=outcome):
                self.assertEqual(delegation.knot_submission(result), outcome)

    def test_an_error_with_exit_status_0_fails(self):
        result = knotc(0, f"error: [{OWNER}] (no such zone found)", "")
        self.assertEqual(delegation.knot_submission(result), "failed")


if __name__ == "__main__":
    unittest.main()
