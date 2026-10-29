import contextlib
import io
import json
import os
import sys
import unittest
import unittest.mock as mock
import urllib.parse
from copy import deepcopy

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import realm_settings as m

MASK = "**********"
KINDS = {
    "default-client-scopes": "defaultClientScopes",
    "optional-client-scopes": "optionalClientScopes",
}


class FakeKeycloak:
    def __init__(self):
        self.clients = {}
        self.scopes = {}
        self.assigned = {}
        self.realms = {}
        self.writes = []
        self._next = 0

    def _id(self, prefix):
        self._next += 1
        return f"{prefix}-{self._next}"

    def add_scope(self, name):
        scope_id = self._id("s")
        self.scopes[scope_id] = {"id": scope_id, "name": name, "protocol": "oidc"}
        return scope_id

    def scope_id(self, name):
        return next(s["id"] for s in self.scopes.values() if s["name"] == name)

    def add_client(self, rep):
        client_id = self._id("c")
        stored = {k: v for k, v in deepcopy(rep).items() if k not in KINDS.values()}
        self.clients[client_id] = {
            **stored,
            "id": client_id,
            "access": {"view": True},
            "attributes": {**stored["attributes"], "realm_client": "false"},
            "redirectUris": list(reversed(stored["redirectUris"])),
        }
        for kind, field in KINDS.items():
            self.assigned[(client_id, kind)] = {
                self.scope_id(name) for name in rep[field]
            }
        return client_id

    def add_realm(self, name, smtp):
        self.realms[name] = {
            "id": name,
            "realm": name,
            "enabled": True,
            "webAuthnPolicyRpEntityName": "keycloak",
            "smtpServer": deepcopy(smtp),
        }

    def shown(self, client_id):
        client = deepcopy(self.clients[client_id])
        if client.get("publicClient") or client.get("bearerOnly"):
            client = {k: v for k, v in client.items() if k != "secret"}
        for kind, field in KINDS.items():
            client[field] = [
                self.scopes[s]["name"] for s in self.assigned[(client_id, kind)]
            ]
        return client

    def call(self, method, path, payload=None, timeout=60):
        route, _, query = path.partition("?")
        parts = route.split("/")
        if method != "GET":
            self.writes.append((method, route, deepcopy(payload)))
        if route == "client-scopes" and method == "GET":
            return [dict(s) for s in self.scopes.values()], ""
        if route == "client-scopes" and method == "POST":
            scope_id = self._id("s")
            self.scopes[scope_id] = {**payload, "id": scope_id}
            return None, scope_id
        if route == "clients" and method == "GET":
            wanted = urllib.parse.parse_qs(query).get("clientId")
            return [
                self.shown(c)
                for c, rep in self.clients.items()
                if wanted is None or rep["clientId"] == wanted[0]
            ], ""
        if route == "clients" and method == "POST":
            if any(c["clientId"] == payload["clientId"] for c in self.clients.values()):
                raise m.KeycloakError(f"POST cymais/{path}: HTTP 409")
            return None, self.add_client(payload)
        if len(parts) == 2 and method == "PUT":
            self.clients[parts[1]] = {
                k: v for k, v in deepcopy(payload).items() if k not in KINDS.values()
            }
            return None, ""
        if len(parts) == 3 and method == "GET":
            return [
                dict(self.scopes[s]) for s in self.assigned[(parts[1], parts[2])]
            ], ""
        if len(parts) == 4 and method == "DELETE":
            self.assigned[(parts[1], parts[2])].discard(parts[3])
            return None, ""
        if len(parts) == 4 and method == "PUT":
            self.assigned[(parts[1], parts[2])].add(parts[3])
            return None, ""
        raise AssertionError(f"unexpected call {method} {path}")

    def admin(self, method, path, payload=None, timeout=60):
        realm = urllib.parse.unquote(path)
        if method == "GET":
            shown = deepcopy(self.realms[realm])
            if "password" in shown["smtpServer"]:
                shown["smtpServer"]["password"] = MASK
            return shown, ""
        if method == "PUT":
            self.writes.append((method, realm, deepcopy(payload)))
            stored = deepcopy(payload)
            if stored["smtpServer"].get("password") == MASK:
                stored["smtpServer"]["password"] = self.realms[realm]["smtpServer"][
                    "password"
                ]
            self.realms[realm] = stored
            return None, ""
        raise AssertionError(f"unexpected admin call {method} {path}")


def _client(**changes):
    return {
        "clientId": "cymais.cloud",
        "publicClient": False,
        "secret": "s3cret",
        "redirectUris": ["https://a.example/*", "https://b.example/*"],
        "attributes": {"frontchannel.logout.url": "https://logout.example/"},
        "protocolMappers": [
            {
                "name": "audience",
                "protocolMapper": "oidc-audience-mapper",
                "config": {"access.token.claim": "true"},
            }
        ],
        "defaultClientScopes": ["profile", "rbac"],
        "optionalClientScopes": ["offline_access"],
        **changes,
    }


def _keycloak():
    kc = FakeKeycloak()
    for name in ("profile", "rbac", "offline_access", "phone"):
        kc.add_scope(name)
    return kc


def _catalog(kc):
    return {s["name"]: s["id"] for s in kc.scopes.values()}


def _deployed(kc, client):
    client_id = kc.add_client(client)
    mapper = kc.clients[client_id]["protocolMappers"][0]
    mapper.update({"id": "pm-1", "protocol": "openid-connect"})
    return client_id


def _converge(kc, desired):
    existing = next(
        (
            kc.shown(c)
            for c, r in kc.clients.items()
            if r["clientId"] == desired["clientId"]
        ),
        None,
    )
    return m.converge_client(kc, desired, existing, _catalog(kc))


class TestMatches(unittest.TestCase):
    def test_equal_values_match(self):
        self.assertTrue(m.matches({"a": [1, {"b": "c"}]}, {"a": [1, {"b": "c"}]}))

    def test_list_order_does_not_count(self):
        self.assertTrue(m.matches(["x", "y"], ["y", "x"]))

    def test_keys_keycloak_adds_do_not_count(self):
        self.assertTrue(m.matches([{"name": "n"}], [{"name": "n", "id": "1"}]))

    def test_an_empty_desired_value_matches_a_key_keycloak_omits(self):
        self.assertTrue(m.matches({"name": "", "mappers": []}, {}))

    def test_a_changed_value_does_not_match(self):
        self.assertFalse(m.matches({"a": {"b": "new"}}, {"a": {"b": "old"}}))

    def test_an_extra_current_list_item_does_not_match(self):
        self.assertFalse(m.matches(["x"], ["x", "y"]))

    def test_a_set_desired_value_does_not_match_a_key_keycloak_omits(self):
        self.assertFalse(m.matches({"secret": "s"}, {}))


class TestConvergeClient(unittest.TestCase):
    def test_an_unchanged_client_is_not_written(self):
        kc = _keycloak()
        _deployed(kc, _client())
        self.assertEqual(_converge(kc, _client()), "unchanged")
        self.assertEqual(kc.writes, [])

    def test_a_drifted_client_is_written_once_and_keeps_its_other_fields(self):
        kc = _keycloak()
        client_id = _deployed(kc, _client())
        drifted = _client(attributes={"frontchannel.logout.url": "https://new/"})
        self.assertEqual(_converge(kc, drifted), "updated")
        self.assertEqual(
            [(w[0], w[1]) for w in kc.writes], [("PUT", f"clients/{client_id}")]
        )
        body = kc.writes[0][2]
        self.assertEqual(body["id"], client_id)
        self.assertEqual(body["attributes"]["realm_client"], "false")
        self.assertEqual(body["attributes"]["frontchannel.logout.url"], "https://new/")

    def test_the_hidden_secret_of_a_public_client_does_not_count_as_drift(self):
        kc = _keycloak()
        _deployed(kc, _client(publicClient=True))
        self.assertEqual(_converge(kc, _client(publicClient=True)), "unchanged")
        self.assertEqual(kc.writes, [])

    def test_a_rotated_secret_of_a_confidential_client_is_written(self):
        kc = _keycloak()
        client_id = _deployed(kc, _client())
        self.assertEqual(_converge(kc, _client(secret="rotated")), "updated")
        self.assertEqual(kc.clients[client_id]["secret"], "rotated")
        self.assertEqual(len(kc.writes), 1)

    def test_an_absent_client_is_created_with_one_post(self):
        kc = _keycloak()
        self.assertEqual(_converge(kc, _client()), "created")
        self.assertEqual([(w[0], w[1]) for w in kc.writes], [("POST", "clients")])

    def test_a_client_another_writer_created_meanwhile_is_updated_instead(self):
        kc = _keycloak()
        _deployed(kc, _client(secret="old"))
        outcome = m.converge_client(kc, _client(), None, _catalog(kc))
        self.assertEqual(outcome, "updated")
        self.assertEqual([w[0] for w in kc.writes], ["POST", "PUT"])

    def test_scope_list_drift_moves_only_the_scopes_and_skips_the_client_put(self):
        kc = _keycloak()
        client_id = _deployed(kc, _client(defaultClientScopes=["profile"]))
        desired = _client(optionalClientScopes=[])
        self.assertEqual(_converge(kc, desired), "updated")
        self.assertEqual(
            sorted((w[0], w[1]) for w in kc.writes),
            [
                (
                    "DELETE",
                    f"clients/{client_id}/optional-client-scopes/{kc.scope_id('offline_access')}",
                ),
                (
                    "PUT",
                    f"clients/{client_id}/default-client-scopes/{kc.scope_id('rbac')}",
                ),
            ],
        )

    def test_an_unknown_scope_is_refused_before_any_scope_moves(self):
        kc = _keycloak()
        client_id = _deployed(kc, _client())
        with self.assertRaises(m.RefusalError) as raised:
            _converge(kc, _client(defaultClientScopes=["profile", "ghost"]))
        self.assertIn("ghost", str(raised.exception))
        self.assertEqual(kc.writes, [])
        self.assertIn(
            kc.scope_id("rbac"), kc.assigned[(client_id, "default-client-scopes")]
        )


class TestCreateScope(unittest.TestCase):
    def test_a_missing_scope_is_created_and_catalogued(self):
        kc = _keycloak()
        catalog = _catalog(kc)
        self.assertEqual(m.create_scope(kc, {"name": "nextcloud"}, catalog), "created")
        self.assertEqual(catalog["nextcloud"], kc.scope_id("nextcloud"))
        self.assertEqual([(w[0], w[1]) for w in kc.writes], [("POST", "client-scopes")])

    def test_an_existing_scope_is_left_alone(self):
        kc = _keycloak()
        outcome = m.create_scope(kc, {"name": "rbac", "protocol": "x"}, _catalog(kc))
        self.assertEqual(outcome, "unchanged")
        self.assertEqual(kc.writes, [])


class TestConvergeRealm(unittest.TestCase):
    def test_matching_mail_settings_without_a_secret_are_not_written(self):
        kc = FakeKeycloak()
        kc.add_realm("master", {"host": "mail.example", "port": "587"})
        outcome = m.converge_realm(
            kc, "master", {"smtpServer": {"host": "mail.example"}}
        )
        self.assertEqual(outcome, "unchanged")
        self.assertEqual(kc.writes, [])

    def test_drifted_mail_settings_are_written_once_into_the_whole_realm(self):
        kc = FakeKeycloak()
        kc.add_realm("master", {"host": "old.example", "port": "587"})
        outcome = m.converge_realm(
            kc, "master", {"smtpServer": {"host": "new.example"}}
        )
        self.assertEqual(outcome, "updated")
        self.assertEqual(len(kc.writes), 1)
        self.assertEqual(
            kc.realms["master"]["smtpServer"], {"host": "new.example", "port": "587"}
        )
        self.assertEqual(kc.realms["master"]["webAuthnPolicyRpEntityName"], "keycloak")

    def test_a_masked_password_is_written_so_rotation_reaches_keycloak(self):
        kc = FakeKeycloak()
        kc.add_realm("cymais", {"host": "mail.example", "password": "old"})
        desired = {"smtpServer": {"host": "mail.example", "password": "new"}}
        self.assertEqual(m.converge_realm(kc, "cymais", desired), "updated")
        self.assertEqual(kc.realms["cymais"]["smtpServer"]["password"], "new")

    def test_mail_settings_of_a_disabled_mailer_leave_the_realm_alone(self):
        kc = FakeKeycloak()
        kc.add_realm("cymais", {"host": "mail.example", "password": "pw"})
        self.assertEqual(
            m.converge_realm(kc, "cymais", {"smtpServer": {}}), "unchanged"
        )
        self.assertEqual(kc.writes, [])


class TestMain(unittest.TestCase):
    def _run(self, kc, spec):
        out, err = io.StringIO(), io.StringIO()
        env = {"KC_URL": "http://kc", "KC_PID": "1", "KC_REALM": "cymais"}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
            mock.patch.object(m.sys, "stdin", io.StringIO(json.dumps(spec))),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = m.main()
        return code, out.getvalue().splitlines(), err.getvalue()

    def _spec(self, clients, smtp):
        return {
            "clientScopes": [{"name": "rbac"}],
            "clients": clients,
            "realms": [
                {"realm": "cymais", "desired": {"smtpServer": smtp}},
                {"realm": "master", "desired": {"smtpServer": smtp}},
            ],
        }

    def _deployment(self):
        kc = _keycloak()
        client_id = _deployed(kc, _client())
        kc.add_realm("cymais", {"host": "mail.example"})
        kc.add_realm("master", {"host": "mail.example"})
        return kc, client_id

    def test_an_unchanged_deployment_writes_nothing(self):
        kc, _ = self._deployment()
        spec = self._spec([_client()], {"host": "mail.example"})
        code, lines, _ = self._run(kc, spec)
        self.assertEqual(code, 0)
        self.assertEqual(kc.writes, [])
        self.assertEqual(lines[-1], "summary created=0 updated=0 unchanged=4 failed=0")

    def test_each_drifted_object_gets_one_write(self):
        kc, client_id = self._deployment()
        drifted = _client(redirectUris=["https://a.example/*"])
        code, lines, _ = self._run(kc, self._spec([drifted], {"host": "new.example"}))
        self.assertEqual(code, 0)
        self.assertEqual(
            [(w[0], w[1]) for w in kc.writes],
            [("PUT", f"clients/{client_id}"), ("PUT", "cymais"), ("PUT", "master")],
        )
        self.assertIn("updated client cymais.cloud", lines)
        self.assertEqual(lines[-1], "summary created=0 updated=3 unchanged=1 failed=0")

    def test_a_refused_client_fails_the_run_and_is_named(self):
        kc, _ = self._deployment()
        refused = _client(defaultClientScopes=["ghost"])
        spec = self._spec([refused], {"host": "mail.example"})
        code, lines, err = self._run(kc, spec)
        self.assertEqual(code, 1)
        self.assertIn("failed client cymais.cloud", lines)
        self.assertIn(
            "client cymais.cloud: client scopes missing in the realm: ghost", err
        )
        self.assertIn("unchanged realm master", lines)

    def test_a_spec_without_realms_fails_before_any_call(self):
        kc, _ = self._deployment()
        spec = {"clientScopes": [], "clients": []}
        code, lines, _ = self._run(kc, spec)
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("listing-failed"))
        self.assertEqual(kc.writes, [])


if __name__ == "__main__":
    unittest.main()
