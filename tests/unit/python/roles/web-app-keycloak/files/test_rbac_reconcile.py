import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import rbac_reconcile as m

LDAP = "ldap-1"


class FakeKeycloak:
    def __init__(self):
        self.groups = {"root": {"id": "root", "name": "roles", "attributes": {}}}
        self.parents = {}
        self.components = {}
        self.syncs = []
        self.failing_syncs = set()
        self._next = 0

    def _id(self, prefix):
        self._next += 1
        return f"{prefix}-{self._next}"

    def add_group(self, name, parent="root", attributes=None):
        group_id = self._id("g")
        self.groups[group_id] = {
            "id": group_id,
            "name": name,
            "attributes": attributes or {},
        }
        self.parents[group_id] = parent
        return group_id

    def add_mapper(self, name, config):
        mapper_id = self._id("c")
        self.components[mapper_id] = {
            "id": mapper_id,
            "name": name,
            "parentId": LDAP,
            "config": config,
        }
        return mapper_id

    def children(self, group_id):
        return [
            dict(g)
            for gid, g in self.groups.items()
            if self.parents.get(gid) == group_id
        ]

    def call(self, method, path, payload=None, timeout=60):
        route = path.split("?", 1)[0]
        if method == "GET" and route == "components":
            return [dict(c) for c in self.components.values()], ""
        if method == "GET" and route == "group-by-path/roles":
            return dict(self.groups["root"]), ""
        if method == "POST" and route == "components":
            mapper_id = self._id("c")
            self.components[mapper_id] = {**payload, "id": mapper_id}
            return None, mapper_id
        if method == "PUT" and route.startswith("components/"):
            self.components[route.split("/")[1]] = dict(payload)
            return None, ""
        if method == "DELETE" and route.startswith("components/"):
            del self.components[route.split("/")[1]]
            return None, ""
        if (
            method == "POST"
            and route.startswith("groups/")
            and route.endswith("/children")
        ):
            return None, self.add_group(payload["name"], route.split("/")[1])
        if method == "GET" and route.startswith("groups/"):
            return json.loads(json.dumps(self.groups[route.split("/")[1]])), ""
        if method == "PUT" and route.startswith("groups/"):
            self.groups[route.split("/")[1]] = dict(payload)
            return None, ""
        if method == "DELETE" and route.startswith("groups/"):
            del self.groups[route.split("/")[1]]
            return None, ""
        if method == "POST" and route.startswith(f"user-storage/{LDAP}/mappers/"):
            mapper_id = route.split("/")[3]
            if mapper_id in self.failing_syncs:
                raise m.KeycloakError("POST sync: HTTP 500")
            self.syncs.append(mapper_id)
            return None, ""
        raise AssertionError(f"unexpected call {method} {path}")


def _payload(app_id, filter_suffix=""):
    return json.dumps(
        {
            "name": f"ldap-roles-{app_id}",
            "parentId": LDAP,
            "providerId": "group-ldap-mapper",
            "config": {
                "groups.path": [f"/roles/{app_id}"],
                "groups.ldap.filter": [f"(cn={app_id}-*){filter_suffix}"],
            },
        }
    )


def _app(app_id, fingerprint="fp-1", filter_suffix=""):
    return m.App(
        app_id, f"ldap-roles-{app_id}", _payload(app_id, filter_suffix), fingerprint
    )


def _reconciler(kc, attempts=2):
    groups = {g["name"]: g["id"] for g in kc.children("root")}
    mappers = {c["name"]: c for c in kc.components.values()}
    return m.Reconciler(kc, LDAP, "root", groups, mappers, attempts, 0, 5)


class TestReconciler(unittest.TestCase):
    def test_a_new_app_gets_its_group_mapper_sync_and_fingerprint(self):
        kc = FakeKeycloak()
        self.assertEqual(_reconciler(kc).run(_app("web-app-a")), "synced")
        group = next(g for g in kc.groups.values() if g["name"] == "web-app-a")
        mapper = next(
            c for c in kc.components.values() if c["name"] == "ldap-roles-web-app-a"
        )
        self.assertEqual(mapper["config"]["groups.path"], ["/roles/web-app-a"])
        self.assertEqual(kc.syncs, [mapper["id"]])
        self.assertEqual(group["attributes"][m.FINGERPRINT], ["fp-1"])

    def test_an_unchanged_app_is_not_synced_again(self):
        kc = FakeKeycloak()
        _reconciler(kc).run(_app("web-app-a"))
        self.assertEqual(_reconciler(kc).run(_app("web-app-a")), "unchanged")
        self.assertEqual(len(kc.syncs), 1)

    def test_a_new_fingerprint_syncs_again(self):
        kc = FakeKeycloak()
        _reconciler(kc).run(_app("web-app-a"))
        self.assertEqual(_reconciler(kc).run(_app("web-app-a", "fp-2")), "synced")
        self.assertEqual(len(kc.syncs), 2)

    def test_a_drifted_mapper_is_updated_and_synced(self):
        kc = FakeKeycloak()
        _reconciler(kc).run(_app("web-app-a"))
        self.assertEqual(
            _reconciler(kc).run(_app("web-app-a", filter_suffix="(drift)")), "synced"
        )
        mapper = next(
            c for c in kc.components.values() if c["name"] == "ldap-roles-web-app-a"
        )
        self.assertEqual(
            mapper["config"]["groups.ldap.filter"], ["(cn=web-app-a-*)(drift)"]
        )

    def test_extra_config_keycloak_adds_does_not_count_as_drift(self):
        kc = FakeKeycloak()
        _reconciler(kc).run(_app("web-app-a"))
        mapper = next(
            c for c in kc.components.values() if c["name"] == "ldap-roles-web-app-a"
        )
        mapper["config"]["mapped.group.attributes"] = [""]
        self.assertEqual(_reconciler(kc).run(_app("web-app-a")), "unchanged")

    def test_a_failed_sync_records_no_fingerprint(self):
        kc = FakeKeycloak()
        group_id = kc.add_group("web-app-a")
        mapper_id = kc.add_mapper(
            "ldap-roles-web-app-a",
            {
                "groups.path": ["/roles/web-app-a"],
                "groups.ldap.filter": ["(cn=web-app-a-*)"],
            },
        )
        kc.failing_syncs.add(mapper_id)
        with self.assertRaises(m.StepError) as raised:
            _reconciler(kc).run(_app("web-app-a"))
        self.assertEqual(raised.exception.step, "sync")
        self.assertNotIn(m.FINGERPRINT, kc.groups[group_id]["attributes"])

    def test_existing_group_attributes_survive_the_fingerprint(self):
        kc = FakeKeycloak()
        kc.add_group("web-app-a", attributes={"LDAP_ID": ["x"]})
        _reconciler(kc).run(_app("web-app-a"))
        group = next(g for g in kc.groups.values() if g["name"] == "web-app-a")
        self.assertEqual(group["attributes"]["LDAP_ID"], ["x"])


class TestHousekeeping(unittest.TestCase):
    def test_orphans_go_and_app_groups_stay(self):
        kc = FakeKeycloak()
        keep = kc.add_group("web-app-a")
        kc.add_group("web-app-a-administrator")
        kc.add_group("administrator")
        kept, failures = m.purge_orphans(kc, "root", {"web-app-a"}, 2)
        self.assertEqual(kept, {"web-app-a": keep})
        self.assertEqual(failures, [])
        self.assertEqual(sorted(g["name"] for g in kc.children("root")), ["web-app-a"])

    def test_the_shared_mapper_is_dropped(self):
        kc = FakeKeycloak()
        kc.add_mapper(m.SHARED_MAPPER, {})
        per_app = kc.add_mapper("ldap-roles-web-app-a", {})
        mappers = m.ldap_mappers(kc, LDAP)
        self.assertEqual(m.drop_shared_mapper(kc, mappers), [])
        self.assertEqual(list(kc.components), [per_app])
        self.assertNotIn(m.SHARED_MAPPER, mappers)

    def test_payload_lines_are_parsed(self):
        encoded = base64.b64encode(_payload("web-app-a").encode()).decode()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write(f"web-app-a ldap-roles-web-app-a {encoded} fp-9\n\n")
        apps = m.read_payloads(handle.name)
        Path(handle.name).unlink()
        self.assertEqual(
            [(a.app_id, a.mapper_name, a.fingerprint) for a in apps],
            [("web-app-a", "ldap-roles-web-app-a", "fp-9")],
        )
        self.assertEqual(json.loads(apps[0].payload)["name"], "ldap-roles-web-app-a")


if __name__ == "__main__":
    unittest.main()
