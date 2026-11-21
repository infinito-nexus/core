from __future__ import annotations

import contextlib
import io
import json
import unittest
import unittest.mock as mock

from ansible.module_utils.testing import patch_module_args

from utils import aws_api

from ._fake_aws import ADMIN, FakeAws, load

mod = load("semaphore_route53_zone_info")

SUBZONE = "ws.example.org"
ZONE_ID = "Z0123456789ABCDEFGHIJ"
NEIGHBOURS = [
    ("ZSIBLING", "example.org."),
    ("ZBELOW", "a.ws.example.org."),
    ("ZLONGER", "ws.example.org.uk."),
    ("ZAFTER", "zz.example.org."),
]


def lookup_findings(lookup, fake):
    """Args:
        lookup: a function of ``(credentials, zone)`` like ``hosted_zone``.
        fake: a fake AWS without zones.

    Returns:
        One message per pool of hosted zones in which ``lookup`` does not
        return the one zone of the exact name or does not refuse none or two.
    """
    findings = []
    cases = {
        "exact": ([(ZONE_ID, f"{SUBZONE}.")], ZONE_ID),
        "beside neighbours": ([*NEIGHBOURS, (ZONE_ID, f"{SUBZONE}.")], ZONE_ID),
        "only neighbours": (NEIGHBOURS, None),
        "two of the name": (
            [(ZONE_ID, f"{SUBZONE}."), ("ZPRIVATE", f"{SUBZONE}.")],
            None,
        ),
        "none": ([], None),
    }
    for label, (zones, expected) in cases.items():
        fake.zones = zones
        try:
            found = lookup(ADMIN, SUBZONE)
        except LookupError:
            found = None
        if found != expected:
            findings.append(f"{label}: found {found}, expected {expected}")
    return findings


class TestHostedZone(unittest.TestCase):
    def setUp(self):
        self.fake = FakeAws()
        patcher = mock.patch.object(aws_api, "send", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.assertEqual(self.fake.leaks, [])

    def test_apply_finds_the_one_hosted_zone_of_the_exact_name(self):
        self.assertEqual(lookup_findings(mod.hosted_zone, self.fake), [])

    def test_the_name_matches_without_case_or_trailing_dot(self):
        self.fake.zones = [(ZONE_ID, "WS.Example.org.")]
        self.assertEqual(mod.hosted_zone(ADMIN, f"{SUBZONE}."), ZONE_ID)

    def test_negative_control_the_first_listed_zone_fails(self):
        def first(credentials, zone):
            root = aws_api.route53(
                credentials, mod.PATH, {"dnsname": zone, "maxitems": mod.MAX_ITEMS}
            )
            held = root.find("HostedZones/HostedZone")
            if held is None:
                raise LookupError(zone)
            return held.findtext("Id").removeprefix(mod.PREFIX)

        self.assertEqual(
            lookup_findings(first, self.fake),
            [
                "only neighbours: found ZBELOW, expected None",
                "two of the name: found Z0123456789ABCDEFGHIJ, expected None",
            ],
        )

    def test_a_wildcard_is_refused_before_any_call(self):
        with self.assertRaises(LookupError):
            mod.hosted_zone(ADMIN, f"*.{SUBZONE}")
        self.assertEqual(self.fake.calls, [])

    def test_the_module_returns_the_zone_id_and_reports_unchanged(self):
        self.fake.zones = [(ZONE_ID, f"{SUBZONE}.")]
        args = {
            "zone": SUBZONE,
            "admin_access_key_id": ADMIN["access_key_id"],
            "admin_secret_access_key": ADMIN["secret_access_key"],
        }
        buffer = io.StringIO()
        with (
            patch_module_args(args),
            contextlib.redirect_stdout(buffer),
            contextlib.suppress(SystemExit),
        ):
            mod.main()
        result = json.loads(buffer.getvalue())
        self.assertEqual((result["zone"], result["zone_id"]), (SUBZONE, ZONE_ID))
        self.assertFalse(result["changed"])
        self.assertNotIn(ADMIN["secret_access_key"], buffer.getvalue())

    def test_a_refusal_fails_the_module_with_the_aws_code(self):
        self.fake.denied.add("ListHostedZonesByName")
        with self.assertRaises(aws_api.AwsError) as caught:
            mod.hosted_zone(ADMIN, SUBZONE)
        self.assertEqual(caught.exception.code, "AccessDenied")


if __name__ == "__main__":
    unittest.main()
