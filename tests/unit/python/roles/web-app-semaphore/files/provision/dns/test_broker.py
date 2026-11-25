from __future__ import annotations

import contextlib
import http.client
import json
import tempfile
import threading
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import ClassVar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from .._fake_provision import (  # noqa: TID252  the hyphenated role dir admits no absolute import
    CREDENTIALS,
    FILES,
    INTERFACE,
    load,
)

dns_broker = load("provision.dns.broker")
dns_scope = dns_broker.dns_scope
remote = dns_broker.remote
session = dns_broker.session

OPENBAO = PROJECT_ROOT / "roles" / "web-app-openbao"
OPENBAO_VARS = load_yaml_str(read_text(str(OPENBAO / ROLE_FILE_VARS_MAIN)))
APPLY = OPENBAO / "tasks" / "workspace" / "apply.yml"
REACH = CREDENTIALS["dns"][dns_broker.FLAVOR]
BROKER = REACH[session.BROKER]
BASE = BROKER["base"]
JSON = {"content-type": dns_broker.JSON}
ZONE = "ws.example.org"
ZONE_ID = "0123456789abcdef0123456789abcdef"
OTHER_ZONE_ID = "fedcba9876543210fedcba9876543210"
ZONE_TOKEN = "cloudflare-zone-token-of-the-platform"
WS_A = "ws-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
WS_B = "ws-9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"
WS_KNOT = "ws-1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"
TOKEN_A = "dns-child-of-ws-a"
TOKEN_B = "dns-child-of-ws-b"
TOKEN_KNOT = "dns-child-of-a-knot-workspace"
TOKENS = {
    TOKEN_A: [f"{WS_A}{dns_scope.POLICY_SUFFIX}"],
    TOKEN_B: [f"{WS_B}{dns_scope.POLICY_SUFFIX}"],
    TOKEN_KNOT: [f"{WS_KNOT}{dns_scope.POLICY_SUFFIX}"],
    "two-policies": [f"{WS_A}{dns_scope.POLICY_SUFFIX}", "default"],
    "transit-child": [f"{WS_A}-transit"],
}
SCOPES = {
    WS_A: {"workspace": WS_A, "zone": ZONE, "zone_id": ZONE_ID},
    WS_B: {"workspace": WS_B, "zone": ZONE, "zone_id": ZONE_ID},
    WS_KNOT: {"workspace": WS_KNOT, "zone": ZONE, "zone_id": ""},
}
OWN = f"shop.{WS_A}.{ZONE}"
FOREIGN = f"shop.{WS_B}.{ZONE}"
OWN_ID = "a" * 32
FOREIGN_ID = "b" * 32
OWN_TXT_ID = "c" * 32
MISSING_ID = "d" * 32
RECORDS = {
    OWN_ID: {"name": OWN, "type": "A"},
    FOREIGN_ID: {"name": FOREIGN, "type": "A"},
    OWN_TXT_ID: {"name": OWN, "type": "TXT"},
}
CLOUDFLARE_ANSWER = b'{"success": true, "result": {}}'
RECORD_CALLS = ("PUT", "PATCH", "DELETE", "GET")
CREATE_PATH = f"/zones/{ZONE_ID}/dns_records"
REFUSED_AUTHORIZATIONS = (
    "Bearer unknown",
    "Bearer two-policies",
    "Bearer transit-child",
    "Bearer ",
    "",
    f"Basic {TOKEN_A}",
)
FOREIGN_PATHS = (
    f"/zones/{ZONE_ID}",
    f"/zones/{ZONE_ID}/dns_records/export",
    f"/zones/{ZONE_ID}/dns_records/{OWN_ID}\n",
    f"/zones/{ZONE_ID}/dns_records/{OWN_ID.upper()}",
    f"/zones/{ZONE_ID}/dns_records/{OWN_ID[:-1]}",
    f"/zones/{ZONE_ID}/dns_records/{OWN_ID}/extra",
    f"/zones/{ZONE_ID}/dns_records/..",
    f"/zones/{ZONE_ID}/dns_records?name={OWN}",
    "/user/tokens/verify",
    f"/zones/{ZONE_ID}/settings",
)


def body(name, kind, **fields):
    return json.dumps({"name": name, "type": kind, **fields}).encode()


def record_body(method, name):
    """Args:
        method: the HTTP method of a call on one record.
        name: the record name a replace carries.

    Returns:
        The body the provider sends with it: the whole record for a
        replace, the changed fields alone for a change, none otherwise.
    """
    if method == "PUT":
        return body(name, "A", content="192.0.2.11")
    if method == "PATCH":
        return json.dumps({"content": "192.0.2.12"}).encode()
    return b""


class FakePlatform:
    """Args:
    failure: what :meth:`opened` raises, None for none.
    """

    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []
        self.read = []
        self.closed = 0

    def caller(self, token):
        if token not in TOKENS:
            raise dns_scope.ScopeError("OpenBao refuses the bearer token")
        return TOKENS[token]

    @contextlib.contextmanager
    def opened(self, workspace):
        self.read.append(workspace)
        try:
            if self.failure is not None:
                raise self.failure
            yield SCOPES[workspace], ZONE_TOKEN
        finally:
            self.closed += 1

    def cloudflare(self, method, zone_id, record_id, token, payload):
        self.calls.append((method, zone_id, record_id, token, payload))
        if method != dns_scope.READ:
            return 200, JSON, CLOUDFLARE_ANSWER
        record = RECORDS.get(record_id) if zone_id == ZONE_ID else None
        if record is None:
            return 404, JSON, b'{"success": false, "result": null}'
        return 200, JSON, json.dumps({"success": True, "result": record}).encode()


def asked(platform, method, path, token=TOKEN_A, payload=b""):
    """Args:
        platform: the :class:`FakePlatform`.
        method: the HTTP method of the call.
        path: its path below the broker's ``base``.
        token: the bearer token the call presents.
        payload: its body.

    Returns:
        :func:`dns_broker.answer` of the call.
    """
    request = dns_broker.requested(method, BASE + path, BASE, payload)
    return dns_broker.answer(request, f"Bearer {token}", platform, INTERFACE)


def lookup(record_id):
    return (dns_scope.READ, ZONE_ID, record_id, ZONE_TOKEN, None)


class TestTheRequest(unittest.TestCase):
    def test_a_create_carries_the_zone_and_the_name_and_type_of_its_body(self):
        request = dns_broker.requested("POST", BASE + CREATE_PATH, BASE, body(OWN, "A"))
        self.assertEqual(
            request,
            {
                "method": "POST",
                "zone_id": ZONE_ID,
                "record_id": "",
                "name": OWN,
                "type": "A",
                "body": body(OWN, "A"),
            },
        )

    def test_an_empty_name_or_type_is_refused_never_skipped(self):
        payloads = (body("", "A"), body(OWN, ""), json.dumps({"name": ""}).encode())
        for method in sorted(dns_broker.FORWARDED):
            for payload in payloads:
                with (
                    self.subTest(method=method, payload=payload),
                    self.assertRaisesRegex(dns_scope.ScopeError, "empty"),
                ):
                    dns_broker.requested(method, BASE + CREATE_PATH, BASE, payload)

    def test_a_key_named_twice_in_any_letter_case_is_refused(self):
        payloads = (
            f'{{"name": "{OWN}", "Name": "{FOREIGN}", "type": "A"}}',
            f'{{"name": "{OWN}", "name": "{FOREIGN}", "type": "A"}}',
            f'{{"name": "{OWN}", "type": "A", "data": {{"x": 1, "X": 2}}}}',
        )
        for payload in payloads:
            with (
                self.subTest(payload=payload),
                self.assertRaisesRegex(dns_scope.ScopeError, "twice"),
            ):
                dns_broker.requested("POST", BASE + CREATE_PATH, BASE, payload.encode())

    def test_a_record_call_carries_its_record_id_and_no_body_of_a_delete(self):
        path = f"{BASE}/zones/{ZONE_ID}/dns_records/{OWN_ID}"
        request = dns_broker.requested("DELETE", path, BASE, body(FOREIGN, "NS"))
        self.assertEqual(request["record_id"], OWN_ID)
        self.assertEqual((request["name"], request["type"]), ("", ""))

    def test_a_call_beside_the_record_api_is_refused(self):
        paths = [BASE + path for path in FOREIGN_PATHS]
        paths += [CREATE_PATH, BASE + CREATE_PATH.lstrip("/")]
        for path in paths:
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(dns_scope.ScopeError, "forwards no GET"),
            ):
                dns_broker.requested("GET", path, BASE, b"")

    def test_negative_control_both_record_paths_pass(self):
        for path in (CREATE_PATH, f"{CREATE_PATH}/{OWN_ID}"):
            with self.subTest(path=path):
                request = dns_broker.requested("GET", BASE + path, BASE, b"")
                self.assertEqual(request["zone_id"], ZONE_ID)

    def test_a_create_or_change_without_a_record_object_is_refused(self):
        payloads = (b"[]", b"no json", b"", body(1, "A"), body(OWN, ["A"]))
        for method in sorted(dns_broker.FORWARDED):
            for payload in payloads:
                with (
                    self.subTest(method=method, payload=payload),
                    self.assertRaises(dns_scope.ScopeError),
                ):
                    dns_broker.requested(method, BASE + CREATE_PATH, BASE, payload)


class TestTheBroker(unittest.TestCase):
    def setUp(self):
        self.platform = FakePlatform()

    def test_an_own_create_is_forwarded_with_the_zone_token(self):
        payload = body(OWN, "A", content="192.0.2.10", ttl=300)
        answer = asked(self.platform, "POST", CREATE_PATH, payload=payload)
        self.assertEqual(answer, (200, JSON, CLOUDFLARE_ANSWER))
        self.assertEqual(
            self.platform.calls, [("POST", ZONE_ID, "", ZONE_TOKEN, payload)]
        )

    def test_cloudflare_receives_the_object_the_scope_check_judged(self):
        raw = f'{{ "name" : "{OWN}" ,\n "type":"A", "content": "192.0.2.10" }}'.encode()
        asked(self.platform, "POST", CREATE_PATH, payload=raw)
        ((*_, forwarded),) = self.platform.calls
        self.assertNotEqual(forwarded, raw)
        self.assertEqual(json.loads(forwarded), json.loads(raw))

    def test_an_own_record_is_changed_read_and_deleted(self):
        for method in RECORD_CALLS:
            with self.subTest(method=method):
                platform = FakePlatform()
                payload = record_body(method, OWN)
                path = f"{CREATE_PATH}/{OWN_ID}"
                status, _, _ = asked(platform, method, path, payload=payload)
                self.assertEqual(status, 200)
                forwarded = payload if method in dns_broker.FORWARDED else None
                call = (method, ZONE_ID, OWN_ID, ZONE_TOKEN, forwarded)
                self.assertEqual(platform.calls, [lookup(OWN_ID), call])

    def test_a_record_of_another_workspace_in_the_shared_zone_is_refused(self):
        for method in RECORD_CALLS:
            with self.subTest(method=method):
                platform = FakePlatform()
                payload = record_body(method, OWN)
                path = f"{CREATE_PATH}/{FOREIGN_ID}"
                with self.assertRaisesRegex(dns_scope.ScopeError, FOREIGN):
                    asked(platform, method, path, payload=payload)
                self.assertEqual(platform.calls, [lookup(FOREIGN_ID)])
                self.assertEqual(platform.closed, len(platform.read))

    def test_a_create_of_a_name_of_another_workspace_is_refused(self):
        for name in (FOREIGN, f"shop.evil-{WS_A}.{ZONE}", f"{WS_A}.{ZONE}"):
            with (
                self.subTest(name=name),
                self.assertRaises(dns_scope.ScopeError),
            ):
                asked(self.platform, "POST", CREATE_PATH, payload=body(name, "A"))
        self.assertEqual(self.platform.calls, [])

    def test_a_rename_of_an_own_record_to_a_foreign_name_is_refused(self):
        payload = json.dumps({"name": FOREIGN}).encode()
        with self.assertRaisesRegex(dns_scope.ScopeError, FOREIGN):
            asked(self.platform, "PATCH", f"{CREATE_PATH}/{OWN_ID}", payload=payload)
        self.assertEqual(self.platform.calls, [lookup(OWN_ID)])

    def test_the_workspace_is_the_one_of_the_token_never_of_the_request(self):
        payload = body(OWN, "A", workspace=WS_B)
        path = f"{CREATE_PATH}/{OWN_ID}"
        with self.assertRaises(dns_scope.ScopeError):
            asked(self.platform, "PUT", path, token=TOKEN_B, payload=payload)
        self.assertEqual(self.platform.read, [WS_B])
        self.assertEqual(self.platform.calls, [lookup(OWN_ID)])

    def test_negative_control_a_broker_ignoring_the_token_changes_a_foreign_record(
        self,
    ):
        path = f"{CREATE_PATH}/{FOREIGN_ID}"
        with mock.patch.object(dns_scope, "workspace_of", return_value=WS_B):
            status, _, _ = asked(self.platform, "DELETE", path, token=TOKEN_A)
        self.assertEqual(status, 200)
        self.assertEqual(self.platform.calls[-1][:3], ("DELETE", ZONE_ID, FOREIGN_ID))

    def test_a_token_of_no_single_caller_policy_reads_nothing(self):
        request = dns_broker.requested("POST", BASE + CREATE_PATH, BASE, body(OWN, "A"))
        for authorization in REFUSED_AUTHORIZATIONS:
            with (
                self.subTest(authorization=authorization),
                self.assertRaises(dns_scope.ScopeError),
            ):
                dns_broker.answer(request, authorization, self.platform, INTERFACE)
        self.assertEqual((self.platform.read, self.platform.calls), ([], []))

    def test_a_record_the_own_zone_does_not_hold_answers_not_found(self):
        status, _, _ = asked(self.platform, "GET", f"{CREATE_PATH}/{MISSING_ID}")
        self.assertEqual(status, dns_broker.MISSING)
        self.assertEqual(self.platform.calls, [lookup(MISSING_ID)])

    def test_another_zone_is_refused_before_any_lookup(self):
        for path in (
            f"/zones/{OTHER_ZONE_ID}/dns_records/{OWN_ID}",
            f"/zones/{OTHER_ZONE_ID}/dns_records",
        ):
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(dns_scope.ScopeError, "is not the zone of"),
            ):
                asked(self.platform, "DELETE", path)
        self.assertEqual(self.platform.calls, [])

    def test_a_workspace_without_a_cloudflare_zone_is_refused(self):
        payload = body(f"shop.{WS_KNOT}.{ZONE}", "A")
        with self.assertRaises(dns_scope.ScopeError):
            asked(self.platform, "POST", CREATE_PATH, token=TOKEN_KNOT, payload=payload)
        self.assertEqual(self.platform.calls, [])

    def test_a_type_no_dns_module_writes_is_refused(self):
        for kind in ("TXT", "NS", "MX"):
            with (
                self.subTest(kind=kind),
                self.assertRaisesRegex(dns_scope.ScopeError, kind),
            ):
                asked(self.platform, "POST", CREATE_PATH, payload=body(OWN, kind))
        with self.assertRaisesRegex(dns_scope.ScopeError, "TXT"):
            asked(self.platform, "DELETE", f"{CREATE_PATH}/{OWN_TXT_ID}")
        self.assertEqual(self.platform.calls, [lookup(OWN_TXT_ID)])


class TestTheHandler(unittest.TestCase):
    def serve(self, platform):
        server = dns_broker.Server(("127.0.0.1", 0), platform, INTERFACE, BASE)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def setUp(self):
        patcher = mock.patch.object(dns_broker.Handler, "log_message")
        patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, platform, name):
        """Args:
            platform: the :class:`FakePlatform` the served broker asks.
            name: the record name of the create.

        Returns:
            ``(status, body)`` of the broker's answer to a create of ws-A.
        """
        port = self.serve(platform)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(connection.close)
        headers = {
            "Authorization": f"Bearer {TOKEN_A}",
            "Content-Type": dns_broker.JSON,
        }
        connection.request("POST", BASE + CREATE_PATH, body(name, "A"), headers)
        answer = connection.getresponse()
        return answer.status, answer.read()

    def test_an_own_create_answers_with_cloudflares_answer(self):
        status, payload = self.create(FakePlatform(), OWN)
        self.assertEqual((status, payload), (200, CLOUDFLARE_ANSWER))

    def test_a_refusal_answers_forbidden_with_a_cloudflare_error_and_no_token(self):
        status, payload = self.create(FakePlatform(), FOREIGN)
        self.assertEqual(status, dns_broker.REFUSED)
        document = json.loads(payload)
        self.assertIs(document["success"], False)
        self.assertTrue(document["errors"][0]["message"].startswith("dns broker: "))
        self.assertNotIn(ZONE_TOKEN.encode(), payload)

    def test_a_platform_failure_answers_bad_gateway(self):
        failure = remote.RemoteError("OpenBao GET provision/dns-scope: HTTP 500")
        status, payload = self.create(FakePlatform(failure), OWN)
        self.assertEqual(status, dns_broker.FAILED)
        self.assertIn(b"HTTP 500", payload)


class StubBao:
    """Args:
    address: the OpenBao origin.
    cafile: its CA bundle.
    """

    made: ClassVar[list] = []
    secrets: ClassVar[dict] = {}

    def __init__(self, address, cafile):
        self.address = address
        self.cafile = cafile
        self.token = ""
        self.logins = []
        self.reads = []
        self.revoked = 0
        StubBao.made.append(self)

    def approle(self, role_id, secret_id):
        self.logins.append((role_id, secret_id))
        self.token = "login-of-the-broker"

    def read(self, path, fields):
        self.reads.append(path)
        return {field: StubBao.secrets[path][field] for field in fields}

    def revoke(self):
        self.revoked += 1

    def policies(self):
        if self.token not in TOKENS:
            raise remote.RemoteError("OpenBao GET auth/token/lookup-self: HTTP 403")
        return TOKENS[self.token]


class TestThePlatform(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.login = Path(directory.name) / "login.json"
        self.login.write_text(json.dumps({"role_id": "role", "secret_id": "secret"}))
        self.scope_path = BROKER["scope"].format(workspace=WS_A)
        self.token_path = REACH["path"].format(zone=ZONE)
        (field,) = REACH["env"].values()
        StubBao.made = []
        StubBao.secrets = {
            self.scope_path: {"zone": ZONE, "zone_id": ZONE_ID},
            self.token_path: {field: ZONE_TOKEN},
        }
        patcher = mock.patch.object(dns_broker.remote, "OpenBao", StubBao)
        patcher.start()
        self.addCleanup(patcher.stop)
        address = "https://openbao.example.org"
        self.platform = dns_broker.Platform(address, "", self.login, REACH)

    def test_the_broker_calls_the_record_api_of_cloudflare(self):
        answer = (200, {}, b"{}")
        with mock.patch.object(
            dns_broker.remote, "exchange", return_value=answer
        ) as exchange:
            self.platform.cloudflare("GET", ZONE_ID, OWN_ID, ZONE_TOKEN, None)
            self.platform.cloudflare("POST", ZONE_ID, "", ZONE_TOKEN, b"{}")
        self.assertEqual(
            [call.args[0] for call in exchange.call_args_list],
            [
                f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records/{OWN_ID}",
                f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records",
            ],
        )

    def test_the_broker_reads_the_scope_and_the_zone_token_with_its_own_login(self):
        with self.platform.opened(WS_A) as (scope, token):
            self.assertEqual(scope, SCOPES[WS_A])
            self.assertEqual(token, ZONE_TOKEN)
        (bao,) = StubBao.made
        self.assertEqual(bao.logins, [("role", "secret")])
        self.assertEqual(bao.reads, [self.scope_path, self.token_path])
        self.assertEqual(bao.revoked, 1)

    def test_the_login_is_revoked_when_the_call_fails(self):
        with self.assertRaises(dns_scope.ScopeError), self.platform.opened(WS_A):
            raise dns_scope.ScopeError("refused")
        self.assertEqual(StubBao.made[0].revoked, 1)

    def test_the_caller_token_is_looked_up_as_itself(self):
        self.assertEqual(self.platform.caller(TOKEN_A), TOKENS[TOKEN_A])
        self.assertEqual(StubBao.made[0].token, TOKEN_A)
        self.assertEqual(StubBao.made[0].logins, [])

    def test_a_token_openbao_refuses_is_a_refusal(self):
        with self.assertRaisesRegex(dns_scope.ScopeError, "refuses the bearer token"):
            self.platform.caller("revoked-child")


class TestTheContract(unittest.TestCase):
    def test_the_scope_is_the_record_workspace_apply_pins(self):
        mount = OPENBAO_VARS["OPENBAO_PLATFORM_MOUNT"]
        prefix = OPENBAO_VARS["OPENBAO_DNS_SCOPE_PREFIX"]
        self.assertEqual(BROKER["scope"], f"{mount}/data/{prefix}/{{workspace}}")

    def test_the_caller_policy_and_role_are_those_apply_writes(self):
        policy = BROKER["policy"].format(workspace=WS_A)
        self.assertEqual(policy, f"{WS_A}{dns_scope.POLICY_SUFFIX}")
        self.assertEqual(BROKER["role"], BROKER["policy"] + "-child")
        child = next(
            task
            for task in load_yaml_str(read_text(str(APPLY)))
            if task.get("register") == "openbao_workspace_child_policy"
        )
        self.assertIn(
            dns_scope.POLICY_SUFFIX.removeprefix("-"),
            [item["suffix"] for item in child["loop"]],
        )
        shell = child["ansible.builtin.shell"]
        self.assertIn("p=ws-{{ WORKSPACE }}-{{ item.suffix }};", shell)
        self.assertIn("r=auth/token/roles/$p-child;", shell)

    def test_the_broker_listens_on_loopback_http_alone(self):
        url = session.broker_url(BROKER)
        self.assertTrue(url.startswith(f"http://{BROKER['listen']}:"))
        self.assertTrue(url.endswith(BASE))
        self.assertTrue(remote._loopback(BROKER["listen"]))

    def test_negative_control_a_wildcard_listen_is_no_loopback(self):
        self.assertFalse(remote._loopback("0.0.0.0"))  # noqa: S104  test string, not a bind

    def test_only_the_record_module_points_its_provider_at_the_broker(self):
        opentofu = FILES / "opentofu"
        source = opentofu / "modules" / "dns-cloudflare" / "main.tf.json"
        module = json.loads(read_text(str(source)))
        self.assertIn(session.BROKER_FILE, module["provider"]["cloudflare"]["base_url"])
        zone = json.loads(read_text(str(opentofu / "zone" / "main.tf.json")))
        self.assertNotIn("base_url", json.dumps(zone.get("provider", {})))


if __name__ == "__main__":
    unittest.main()
