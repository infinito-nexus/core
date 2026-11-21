"""The service the Loki vhost forwards pushes to joins the reverse proxy's network."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVER, ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles" / "web-svc-loki"
SERVICE_START = re.compile(r"\{% set service_name = '([a-z0-9_-]+)' %\}")
NETWORKS_CALL = re.compile(r"lookup\('container_networks'([^)]*)\)")


def _service_blocks(text: str) -> dict[str, str]:
    """Template text of each service, keyed by its ``service_name``.

    Args:
        text: the compose template.
    """
    starts = list(SERVICE_START.finditer(text))
    ends = [match.start() for match in starts[1:]] + [len(text)]
    return {
        match.group(1): text[match.end() : end]
        for match, end in zip(starts, ends, strict=True)
    }


def _networks_kwargs(block: str) -> str:
    """Keyword arguments of the block's ``container_networks`` lookup.

    Args:
        block: one service's template text.

    Raises:
        AssertionError: the block renders no ``container_networks`` lookup.
    """
    call = NETWORKS_CALL.search(block)
    if call is None:
        raise AssertionError("the service renders no container_networks lookup")
    return call.group(1)


def _reaches_reverse_proxy(kwargs: str) -> bool:
    """Whether a ``container_networks`` call keeps the reverse proxy's network.

    Args:
        kwargs: the call's keyword arguments as template text.
    """
    return "own_network_only=True" not in kwargs or "reverse_proxy=True" in kwargs


class TestGatewayNetworks(unittest.TestCase):
    def test_the_vhost_upstream_joins_the_reverse_proxy_network(self):
        upstream = load_yaml(str(ROLE / ROLE_FILE_META_SERVER))["vhosts"]["default"][
            "service_key"
        ]
        blocks = _service_blocks(read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE)))
        self.assertIn(upstream, blocks)
        self.assertTrue(
            _reaches_reverse_proxy(_networks_kwargs(blocks[upstream])),
            f"openresty proxies pushes to loki_{upstream}, which own_network_only "
            "keeps off the reverse proxy network in swarm, so every push answers 502",
        )

    def test_negative_control_an_own_network_only_upstream_is_caught(self):
        block = _service_blocks(
            "{% set service_name = 'gateway' %}\n"
            "    {{ lookup('container_networks', own_network_only=True, "
            "provider_self_alias=False) | indent(4) }}\n"
        )["gateway"]
        self.assertFalse(_reaches_reverse_proxy(_networks_kwargs(block)))


if __name__ == "__main__":
    unittest.main()
