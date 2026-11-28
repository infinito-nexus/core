import tempfile
import unittest
from pathlib import Path

from ._fixtures import APPVIEW, DID, _record, _uri, load

clients = load("clients")
cycle_module = load("cycle")
store = load("store")


class FakePds:
    def __init__(self):
        self.repos_list = []
        self.records = {}
        self.event_calls = []

    def repos(self):
        return list(self.repos_list)

    def events(self, did):
        self.event_calls.append(did)
        return list(self.records.get(did, []))


class FakeMobilizon:
    def __init__(self, missing=()):
        self.calls = []
        self.missing = set(missing)
        self.next_id = 100

    def create(self, payload):
        self.next_id += 1
        self.calls.append(("create", str(self.next_id), payload))
        return str(self.next_id)

    def update(self, event_id, payload):
        if event_id in self.missing:
            raise clients.MissingEventError(f"Event {event_id} not found")
        self.calls.append(("update", event_id, payload))

    def delete(self, event_id):
        if event_id in self.missing:
            raise clients.MissingEventError(f"Event {event_id} not found")
        self.calls.append(("delete", event_id, None))


class TestPlan(unittest.TestCase):
    def test_plan_creates_updates_deletes_and_keeps(self):
        mirrored = {
            _uri("same"): ("cid-same", "1"),
            _uri("changed"): ("cid-old", "2"),
            _uri("gone"): ("cid-gone", "3"),
        }
        records = [
            {"uri": _uri("same"), "cid": "cid-same", "value": {}},
            {"uri": _uri("changed"), "cid": "cid-new", "value": {"n": 1}},
            {"uri": _uri("new"), "cid": "cid-n", "value": {"n": 2}},
        ]
        actions = cycle_module.plan(mirrored, records)
        self.assertEqual(
            [(a.kind, a.at_uri, a.event_id) for a in actions],
            [
                ("update", _uri("changed"), "2"),
                ("create", _uri("new"), None),
                ("delete", _uri("gone"), "3"),
            ],
        )

    def test_plan_is_empty_when_everything_is_mirrored(self):
        mirrored = {_uri("a"): ("cid-a", "1")}
        records = [{"uri": _uri("a"), "cid": "cid-a", "value": {}}]
        self.assertEqual(cycle_module.plan(mirrored, records), [])


class TestStoreAndCycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = store.Store(str(Path(self.tmp.name) / "state.sqlite"))
        self.pds = FakePds()
        self.sink = FakeMobilizon()
        self.logins = 0
        self.lines = []

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def factory(self):
        self.logins += 1
        return self.sink

    def cycle(self, now=1000.0):
        return cycle_module.run_cycle(
            self.store, self.pds, self.factory, APPVIEW, now, self.lines.append
        )

    def publish(self, rev, records):
        self.pds.repos_list = [{"did": DID, "rev": rev, "active": True}]
        self.pds.records[DID] = records

    def test_full_lifecycle_creates_updates_and_deletes(self):
        self.publish("rev1", [{"uri": _uri("a"), "cid": "c1", "value": _record()}])
        self.assertEqual(self.cycle(), 1)
        self.assertEqual(self.sink.calls[0][0], "create")
        self.assertEqual(self.store.mirrors(DID), {_uri("a"): ("c1", "101")})
        self.assertEqual(
            self.store.mirrored_from("101"), (_uri("a"), store.ORIGIN_ATPROTO)
        )

        self.assertEqual(self.cycle(), 0)
        self.assertEqual(self.pds.event_calls, [DID])

        self.publish(
            "rev2", [{"uri": _uri("a"), "cid": "c2", "value": _record(name="Renamed")}]
        )
        self.assertEqual(self.cycle(), 1)
        self.assertEqual(self.sink.calls[1][:2], ("update", "101"))
        self.assertEqual(self.sink.calls[1][2]["title"], "Renamed")
        self.assertEqual(self.store.mirrors(DID), {_uri("a"): ("c2", "101")})

        self.publish("rev3", [])
        self.assertEqual(self.cycle(), 1)
        self.assertEqual(self.sink.calls[2], ("delete", "101", None))
        self.assertEqual(self.store.mirrors(DID), {})
        self.assertIsNone(self.store.mirrored_from("101"))
        self.assertEqual(self.logins, 3)

    def test_unchanged_pds_neither_logs_in_nor_lists_records(self):
        self.publish("rev1", [])
        self.store.set_rev(DID, "rev1")
        self.assertEqual(self.cycle(), 0)
        self.assertEqual(self.logins, 0)
        self.assertEqual(self.pds.event_calls, [])

    def test_inactive_repository_is_left_alone(self):
        self.publish("rev1", [{"uri": _uri("a"), "cid": "c1", "value": _record()}])
        self.pds.repos_list[0]["active"] = False
        self.assertEqual(self.cycle(), 0)
        self.assertEqual(self.sink.calls, [])

    def test_unmappable_record_is_logged_not_mirrored(self):
        self.publish(
            "rev1", [{"uri": _uri("a"), "cid": "c1", "value": _record(startsAt=None)}]
        )
        self.assertEqual(self.cycle(), 0)
        self.assertEqual(self.sink.calls, [])
        self.assertTrue(
            any("not mirrored: startsAt is missing" in line for line in self.lines)
        )

    def test_unmapped_fields_are_logged_by_name(self):
        self.publish(
            "rev1",
            [{"uri": _uri("a"), "cid": "c1", "value": _record(rsvpExpected=True)}],
        )
        self.cycle()
        self.assertTrue(
            any(
                "without a Mobilizon counterpart: createdAt, rsvpExpected" in line
                for line in self.lines
            )
        )

    def test_failed_mutation_keeps_the_rev_and_written_rows(self):
        class Failing(FakeMobilizon):
            def create(self, payload):
                if self.calls:
                    raise clients.BridgeError("Mobilizon is down")
                return super().create(payload)

        self.sink = Failing()
        self.publish(
            "rev1",
            [
                {"uri": _uri("a"), "cid": "c1", "value": _record()},
                {"uri": _uri("b"), "cid": "c2", "value": _record()},
            ],
        )
        with self.assertRaises(clients.BridgeError):
            self.cycle()
        self.assertIsNone(self.store.rev(DID))
        self.assertEqual(set(self.store.mirrors(DID)), {_uri("a")})
        self.assertIsNone(self.store.last_beat())

        self.sink = FakeMobilizon()
        self.sink.next_id = 200
        self.assertEqual(self.cycle(), 1)
        self.assertEqual([call[0] for call in self.sink.calls], ["create"])
        self.assertEqual(set(self.store.mirrors(DID)), {_uri("a"), _uri("b")})
        self.assertEqual(self.store.rev(DID), "rev1")

    def test_event_deleted_in_mobilizon_is_recreated_on_update_and_forgotten_on_delete(
        self,
    ):
        self.store.put(_uri("a"), "c1", "7", 1.0)
        self.store.put(_uri("b"), "c1", "8", 1.0)
        self.sink = FakeMobilizon(missing={"7", "8"})
        self.publish("rev1", [{"uri": _uri("a"), "cid": "c2", "value": _record()}])
        self.assertEqual(self.cycle(), 2)
        self.assertEqual([call[0] for call in self.sink.calls], ["create"])
        self.assertEqual(self.store.mirrors(DID), {_uri("a"): ("c2", "101")})

    def test_health_follows_the_heartbeat(self):
        self.assertFalse(cycle_module.healthy(self.store, 1000.0, 60))
        self.publish("rev1", [])
        self.cycle(now=1000.0)
        self.assertTrue(cycle_module.healthy(self.store, 1180.0, 60))
        self.assertFalse(cycle_module.healthy(self.store, 1181.0, 60))


if __name__ == "__main__":
    unittest.main()
