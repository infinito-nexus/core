import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT
from ._fixtures import APPVIEW, DID, _record, _uri, load

ROLE = PROJECT_ROOT / "roles" / "web-app-atmo"
mapping = load("mapping")


class TestMapEvent(unittest.TestCase):
    def test_in_person_event_maps_every_mapped_field(self):
        mapped = mapping.map_event(_record(), _uri("r1"), APPVIEW)
        payload = mapped.payload
        self.assertEqual(payload["title"], "Beaver meetup")
        self.assertEqual(payload["beginsOn"], "2026-11-05T17:00:00Z")
        self.assertEqual(payload["endsOn"], "2026-11-05T20:00:00Z")
        self.assertEqual(payload["status"], "CONFIRMED")
        self.assertEqual(payload["visibility"], "PUBLIC")
        self.assertFalse(payload["draft"])
        self.assertIsNone(payload["onlineAddress"])
        self.assertEqual(
            payload["physicalAddress"],
            {
                "street": "Damm 1",
                "locality": "Berlin",
                "postalCode": "10115",
                "country": "DE",
                "description": "The lodge",
                "geom": "13.4;52.52",
            },
        )
        self.assertIn(
            "<p>Bring wood.</p><p>And &lt;snacks&gt;.</p>", payload["description"]
        )
        self.assertIn(f'href="{APPVIEW}/p/{DID}/e/r1"', payload["description"])
        self.assertIn(
            'href="https://beavers.example.org/meetup"', payload["description"]
        )
        self.assertEqual(mapped.unmapped, ["createdAt"])

    def test_virtual_event_maps_online_address_and_reports_the_address(self):
        record = _record(
            mode=f"{mapping.TOKEN_PREFIX}virtual",
            locations=[
                {"$type": mapping.ADDRESS_LOCATION, "locality": "Berlin"},
                {"$type": mapping.URI_LOCATION, "uri": "https://meet.example.org/room"},
            ],
        )
        mapped = mapping.map_event(record, _uri("r2"), APPVIEW)
        self.assertEqual(
            mapped.payload["onlineAddress"], "https://meet.example.org/room"
        )
        self.assertIsNone(mapped.payload["physicalAddress"])
        self.assertIn(f"locations[0]:{mapping.ADDRESS_LOCATION}", mapped.unmapped)

    def test_hybrid_event_maps_both_and_reports_extensions(self):
        record = _record(
            mode=f"{mapping.TOKEN_PREFIX}hybrid",
            rsvpExpected=True,
            additionalData={"x": 1},
            locations=[
                {"$type": mapping.URI_LOCATION, "uri": "https://meet.example.org/room"},
                {"$type": mapping.ADDRESS_LOCATION, "locality": "Berlin"},
                {
                    "$type": "community.lexicon.location.hthree",
                    "value": "8a1fb46622dffff",
                },
            ],
        )
        mapped = mapping.map_event(record, _uri("r3"), APPVIEW)
        self.assertEqual(
            mapped.payload["onlineAddress"], "https://meet.example.org/room"
        )
        self.assertEqual(mapped.payload["physicalAddress"], {"locality": "Berlin"})
        self.assertEqual(
            mapped.unmapped,
            [
                "additionalData",
                "createdAt",
                "rsvpExpected",
                "locations[2]:community.lexicon.location.hthree",
            ],
        )

    def test_missing_status_and_mode_take_the_lexicon_defaults(self):
        record = _record()
        del record["status"]
        del record["mode"]
        payload = mapping.map_event(record, _uri("r4"), APPVIEW).payload
        self.assertEqual(payload["status"], "CONFIRMED")
        self.assertIsNotNone(payload["physicalAddress"])

    def test_status_tokens_map_onto_mobilizon_statuses(self):
        expected = {
            "scheduled": "CONFIRMED",
            "rescheduled": "CONFIRMED",
            "planned": "TENTATIVE",
            "postponed": "TENTATIVE",
            "cancelled": "CANCELLED",
        }
        for token, status in expected.items():
            with self.subTest(token=token):
                record = _record(status=f"{mapping.TOKEN_PREFIX}{token}")
                self.assertEqual(
                    mapping.map_event(record, _uri("r5"), APPVIEW).payload["status"],
                    status,
                )

    def test_unmappable_records_are_refused(self):
        cases = {
            "no name": _record(name=" "),
            "no start": _record(startsAt=None),
            "naive start": _record(startsAt="2026-11-05T18:00:00"),
            "garbled start": _record(startsAt="soon"),
            "end before start": _record(endsAt="2026-11-05T10:00:00Z"),
            "unknown status": _record(status=f"{mapping.TOKEN_PREFIX}maybe"),
            "foreign status": _record(status="CONFIRMED"),
            "unknown mode": _record(mode=f"{mapping.TOKEN_PREFIX}metaverse"),
            "bad geo": _record(
                locations=[
                    {
                        "$type": "community.lexicon.location.geo",
                        "latitude": "n",
                        "longitude": "e",
                    }
                ]
            ),
        }
        for label, record in cases.items():
            with self.subTest(label), self.assertRaises(mapping.UnmappableError):
                mapping.map_event(record, _uri("r6"), APPVIEW)

    def test_malformed_at_uri_is_refused(self):
        with self.assertRaises(mapping.UnmappableError):
            mapping.map_event(_record(), "https://example.org/not-an-at-uri", APPVIEW)


class TestBridgeDocumentation(unittest.TestCase):
    def test_every_lexicon_field_is_mapped_or_listed_as_unmapped(self):
        text = read_text(str(ROLE / "Bridge.md"))
        for name in [
            *sorted(mapping.MAPPED_FIELDS - {"$type"}),
            "createdAt",
            "rsvpExpected",
        ]:
            with self.subTest(field=name):
                self.assertIn(f"`{name}", text)
        self.assertIn("community.lexicon.location.hthree", text)


if __name__ == "__main__":
    unittest.main()
