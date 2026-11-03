from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
TASKS = ROLE / "tasks"

filter_loader.add_directory(str(ROLE / "filter_plugins"))

SECURITY_FACTS = (
    "🔍 Resolve Stalwart's current ban periods, unlisted addresses and HTTP settings"
)
ALIAS_PLAN = "🔍 Plan the alias changes"
WEBADMIN_APPS = "🔍 Resolve the WebUI Application record"
WEBADMIN_CLIENTS = "🔍 Resolve the WebUI OAuth client"
OIDC_FACTS = "🔍 Resolve the Keycloak OIDC directory id (if any) and built-in role ids"

SECURITY_VARIABLES = {
    "stalwart_jmap": {
        "methodResponses": [
            ["x:Security/get", {"list": [{"banPeriod": "1d", "other": 1}]}, "Security"],
            ["x:AllowedIp/get", {"list": [{"address": "10.0.0.1"}]}, "AllowedIp"],
            ["x:Http/get", {"list": [{"useXForwarded": True, "x": 2}]}, "Http"],
        ]
    },
    "STALWART_BAN_PERIODS": {"banPeriod": "1d"},
    "STALWART_ALLOWED_IPS": ["10.0.0.1", "10.0.0.2"],
    "STALWART_HTTP_SETTINGS": {"useXForwarded": True},
}


def _render(template, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _flatten(tasks: list[dict]) -> list[dict]:
    flat = []
    for task in tasks:
        flat.append(task)
        flat.extend(_flatten(task.get("block") or []))
    return flat


def _task(path: str, name: str) -> dict:
    tasks = _flatten(load_yaml_any(str(TASKS / path), default_if_missing=[]))
    return next(t for t in tasks if t.get("name") == name)


def _fact(path: str, name: str, fact: str, **variables):
    return _render(_task(path, name)["ansible.builtin.set_fact"][fact], **variables)


class TestSecurityFactsReadTheirOwnResponse(unittest.TestCase):
    def test_ban_periods_come_from_the_security_response(self):
        self.assertEqual(
            _fact(
                "security.yml",
                SECURITY_FACTS,
                "stalwart_ban_periods_current",
                **SECURITY_VARIABLES,
            ),
            {"banPeriod": "1d"},
        )

    def test_missing_addresses_come_from_the_allowed_ip_response(self):
        self.assertEqual(
            _fact(
                "security.yml",
                SECURITY_FACTS,
                "stalwart_allowed_ips_missing",
                **SECURITY_VARIABLES,
            ),
            ["10.0.0.2"],
        )

    def test_http_settings_come_from_the_http_response(self):
        self.assertEqual(
            _fact(
                "security.yml",
                SECURITY_FACTS,
                "stalwart_http_settings_current",
                **SECURITY_VARIABLES,
            ),
            {"useXForwarded": True},
        )


class TestBatchedFactsReadTheirOwnResponse(unittest.TestCase):
    def test_alias_plan_reads_domains_then_mailing_lists(self):
        plan = _fact(
            "15_aliases.yml",
            ALIAS_PLAN,
            "stalwart_alias_plan",
            stalwart_jmap={
                "methodResponses": [
                    [
                        "x:Domain/get",
                        {"list": [{"id": "d1", "name": "infinito.test"}]},
                        "Domain",
                    ],
                    [
                        "x:MailingList/get",
                        {
                            "list": [
                                {
                                    "id": "m9",
                                    "name": "gone",
                                    "domainId": "d1",
                                    "description": "marker",
                                }
                            ]
                        },
                        "MailingList",
                    ],
                ]
            },
            STALWART_ALIASES=[
                {
                    "address": "info@infinito.test",
                    "local": "info",
                    "domain": "infinito.test",
                    "destinations": ["a@example.org"],
                }
            ],
            STALWART_ALIAS_DESCRIPTION="marker",
        )
        self.assertEqual(next(iter(plan["create"].values()))["domainId"], "d1")
        self.assertEqual(plan["destroy"], ["m9"])

    def test_webadmin_reads_applications_then_oauth_clients(self):
        responses = [
            [
                "x:Application/get",
                {"list": [{"id": "a1", "description": "WebUI", "urlPrefix": {}}]},
                "Application",
            ],
            [
                "x:OAuthClient/get",
                {"list": [{"id": "o1", "clientId": "stalwart-webui"}]},
                "OAuthClient",
            ],
        ]
        apps = _fact(
            "02_webadmin.yml",
            WEBADMIN_APPS,
            "stalwart_webui_apps",
            stalwart_jmap={"methodResponses": responses},
            STALWART_WEBUI_APP_DESCRIPTION="WebUI",
        )
        clients = _fact(
            "02_webadmin.yml",
            WEBADMIN_CLIENTS,
            "stalwart_webui_oauth_clients",
            stalwart_jmap={"methodResponses": responses},
            STALWART_WEBUI_OAUTH_CLIENT_ID="stalwart-webui",
        )
        self.assertEqual([a["id"] for a in apps], ["a1"])
        self.assertEqual([c["id"] for c in clients], ["o1"])

    def test_oidc_reads_directories_then_roles(self):
        variables = {
            "stalwart_jmap": {
                "methodResponses": [
                    [
                        "x:Directory/get",
                        {
                            "list": [
                                {
                                    "id": "k1",
                                    "@type": "Oidc",
                                    "issuerUrl": "https://auth.test/realms/r",
                                }
                            ]
                        },
                        "Directory",
                    ],
                    [
                        "x:Role/get",
                        {
                            "list": [
                                {"id": "r1", "description": "User"},
                                {"id": "r2", "description": "Group"},
                                {"id": "r3", "description": "Tenant Administrator"},
                                {"id": "r4", "description": "System Administrator"},
                            ]
                        },
                        "Role",
                    ],
                ]
            },
            "OIDC": {"CLIENT": {"ISSUER_URL": "https://auth.test/realms/r"}},
        }
        resolved = {
            fact: _fact("06_oidc.yml", OIDC_FACTS, fact, **variables)
            for fact in (
                "stalwart_oidc_dir_id",
                "stalwart_role_user",
                "stalwart_role_group",
                "stalwart_role_tenant",
                "stalwart_role_admin",
            )
        }
        self.assertEqual(
            resolved,
            {
                "stalwart_oidc_dir_id": "k1",
                "stalwart_role_user": "r1",
                "stalwart_role_group": "r2",
                "stalwart_role_tenant": "r3",
                "stalwart_role_admin": "r4",
            },
        )


if __name__ == "__main__":
    unittest.main()
