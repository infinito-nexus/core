from __future__ import annotations

import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.base import _render_with_templar
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ADDON = (
    PROJECT_ROOT
    / "roles/web-app-wordpress/meta/addons/daggerhart-openid-connect-generic.yml"
)
REALM = PROJECT_ROOT / "roles/web-app-keycloak/templates/import/realm.json.j2"
OIDC_VARS = PROJECT_ROOT / "group_vars/all/11_oidc.yml"
EMAIL_CLAIM = re.compile(
    r'"user\.attribute":\s*"email",[^{}]*?"claim\.name":\s*"(?P<claim>[^"]+)"'
)


def _email_format() -> str:
    addon = load_yaml_any(str(ADDON), default_if_missing={})
    attributes = load_yaml_any(str(OIDC_VARS), default_if_missing={})["defaults_oidc"][
        "ATTRIBUTES"
    ]
    return str(
        _render_with_templar(
            addon["config"]["oidc_settings"]["email_format"],
            templar=Templar(loader=DataLoader(), variables={}),
            variables={"OIDC": {"ATTRIBUTES": attributes}},
        )
    )


def _email_claim_keycloak_emits() -> str:
    match = EMAIL_CLAIM.search(read_text(str(REALM)))
    assert match, f"{REALM} must map the email user attribute to a claim"
    return match.group("claim")


class TestOidcEmailFormat(unittest.TestCase):
    def test_the_email_format_reads_the_claim_keycloak_emits(self):
        self.assertEqual(_email_format(), "{" + _email_claim_keycloak_emits() + "}")


if __name__ == "__main__":
    unittest.main()
