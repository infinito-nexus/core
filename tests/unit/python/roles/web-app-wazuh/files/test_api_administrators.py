from __future__ import annotations

import base64
import io
import json
import runpy
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-wazuh/files/python/api_administrators.py"
ROLES = ["admin", "/roles/web-app-wazuh/administrator", "web-app-wazuh-administrator"]
RULE = {"OR": [{"FIND": {"backend_roles": role}} for role in ROLES]}
ENV = {
    "API_USERNAME": "wazuh-wui",
    "API_PASSWORD": "s3cret",
    "WAZUH_RBAC_RULE_NAME": "infinito_administrators",
    "WAZUH_RBAC_BACKEND_ROLES": json.dumps(ROLES),
}


class FakeApi:
    def __init__(self, rules: list[dict], admin_rules: list[int]):
        self.rules = rules
        self.roles = [
            {"id": 1, "name": "administrator", "rules": admin_rules},
            {"id": 2, "name": "readonly", "rules": []},
        ]
        self.writes: list[tuple[str, str, object]] = []
        self.basic = None

    def __call__(self, request, context=None):
        method, path = (
            request.get_method(),
            request.full_url.removeprefix("https://localhost:55000"),
        )
        body = json.loads(request.data) if request.data else None
        if path == "/security/user/authenticate":
            self.basic = request.get_header("Authorization")
            data = {"token": "jwt"}
        elif method == "GET" and path.startswith("/security/rules"):
            data = {"affected_items": self.rules}
        elif method == "GET" and path.startswith("/security/roles"):
            data = {"affected_items": self.roles}
        elif method == "POST" and path == "/security/rules":
            created = {"id": 100, "name": body["name"], "rule": body["rule"]}
            self.rules.append(created)
            self.writes.append((method, path, body))
            data = {"affected_items": [created]}
        else:
            self.writes.append((method, path, body))
            data = {"affected_items": []}
        return io.BytesIO(json.dumps({"data": data}).encode())


def _run(api: FakeApi) -> str:
    out = io.StringIO()
    with (
        patch("urllib.request.urlopen", api),
        patch.dict("os.environ", ENV),
        redirect_stdout(out),
    ):
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
    return out.getvalue().strip()


class TestApiAdministrators(unittest.TestCase):
    def test_fresh_manager_gets_the_rule_and_its_administrator_link(self):
        api = FakeApi(
            rules=[
                {
                    "id": 2,
                    "name": "wui_opensearch_admin",
                    "rule": {"FIND": {"user_name": "admin"}},
                }
            ],
            admin_rules=[2],
        )
        self.assertEqual(_run(api), "CHANGED")
        self.assertEqual(
            api.writes[0],
            (
                "POST",
                "/security/rules",
                {"name": "infinito_administrators", "rule": RULE},
            ),
        )
        self.assertEqual(
            api.writes[1][:2], ("POST", "/security/roles/1/rules?rule_ids=100")
        )

    def test_converged_manager_reports_ok_without_writing(self):
        api = FakeApi(
            rules=[{"id": 100, "name": "infinito_administrators", "rule": RULE}],
            admin_rules=[2, 100],
        )
        self.assertEqual(_run(api), "OK")
        self.assertEqual(api.writes, [])

    def test_a_drifted_rule_is_rewritten_in_place(self):
        api = FakeApi(
            rules=[
                {
                    "id": 100,
                    "name": "infinito_administrators",
                    "rule": {"FIND": {"backend_roles": "old"}},
                }
            ],
            admin_rules=[100],
        )
        self.assertEqual(_run(api), "CHANGED")
        self.assertEqual(api.writes, [("PUT", "/security/rules/100", {"rule": RULE})])

    def test_an_unlinked_rule_is_linked_to_the_administrator_role(self):
        api = FakeApi(
            rules=[{"id": 100, "name": "infinito_administrators", "rule": RULE}],
            admin_rules=[2],
        )
        self.assertEqual(_run(api), "CHANGED")
        self.assertEqual(
            api.writes[0][:2], ("POST", "/security/roles/1/rules?rule_ids=100")
        )

    def test_the_api_account_authenticates_with_basic_auth_from_the_environment(self):
        api = FakeApi(
            rules=[{"id": 100, "name": "infinito_administrators", "rule": RULE}],
            admin_rules=[100],
        )
        _run(api)
        self.assertEqual(
            api.basic, "Basic " + base64.b64encode(b"wazuh-wui:s3cret").decode()
        )


if __name__ == "__main__":
    unittest.main()
