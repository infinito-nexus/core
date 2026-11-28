from __future__ import annotations

import copy
import unittest

from jinja2 import Environment, nodes

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_DOMAINS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_ROLE = PROJECT_ROOT / "roles/svc-ai-litellm"
_ENV_TEMPLATE = _ROLE / "templates/env.j2"
_GATEWAY = "litellm"
_ISSUER_KEY = "GENERIC_TOKEN_ENDPOINT"


def env_keys(env_text: str) -> set[str]:
    """
    Args:
      env_text: the gateway container's env template.

    Returns:
      every key a line of the rendered env file can assign.
    """
    tree = Environment(autoescape=True).parse(env_text)
    return {
        line.split("=", 1)[0]
        for data in tree.find_all(nodes.TemplateData)
        for line in data.data.splitlines()
        if "=" in line
    }


def missing_ca_client(services: dict, keys: set[str], has_domain: bool) -> list[str]:
    """
    Args:
      services: the role's meta/services.yml mapping.
      keys: the env keys the gateway container's env template assigns.
      has_domain: whether the role serves a domain of its own.

    Returns:
      the gateway service name when the container exchanges the SSO code at the
      issuer's token endpoint while ca_injected cannot hand it the self-signed CA.
    """
    if has_domain or _ISSUER_KEY not in keys:
        return []
    return [] if services[_GATEWAY].get("ca_client") is True else [_GATEWAY]


class TestCaClient(unittest.TestCase):
    def setUp(self) -> None:
        self.services = load_yaml(str(_ROLE / ROLE_FILE_META_SERVICES))
        self.keys = env_keys(read_text(str(_ENV_TEMPLATE)))
        self.has_domain = (_ROLE / ROLE_FILE_META_DOMAINS).is_file()

    def test_the_gateway_trusts_the_self_signed_issuer(self) -> None:
        self.assertEqual(
            missing_ca_client(self.services, self.keys, self.has_domain), []
        )

    def test_negative_control_without_ca_client_the_token_exchange_is_unverifiable(
        self,
    ) -> None:
        planted = copy.deepcopy(self.services)
        planted[_GATEWAY].pop("ca_client", None)
        self.assertEqual(
            missing_ca_client(planted, self.keys, self.has_domain), [_GATEWAY]
        )


if __name__ == "__main__":
    unittest.main()
