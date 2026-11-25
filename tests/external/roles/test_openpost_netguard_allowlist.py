"""The pinned OpenPost still offers no switch to allow private networks.

web-app-openpost sends OpenPost's requests to its sibling roles through a
relay on 192.88.99.0/24, a block outside the role subnet pool, because
OpenPost's netguard refuses every private address and offers no switch
(infinito-nexus/core#2867, getopenpost/openpost#533). Once the pinned OpenPost
reads such a switch, the relay and the out-of-pool subnet are obsolete, and
this test fails so the workaround goes instead of outliving its reason.

The switch would live in the upstream repository at the pinned tag, so the
check is external: it fetches OpenPost's config loader of that tag from
raw.githubusercontent.com and looks for any ``OPENPOST_*PRIVATE*`` variable,
because the name may change during upstream review. A refused connection, a
timeout, a rate limit or a server error skips it as unverified; any other
status than 200 fails it.
"""

from __future__ import annotations

import re
import unittest

import requests

from utils.annotations.message import warning
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_SERVICES = PROJECT_ROOT / "roles/web-app-openpost" / ROLE_FILE_META_SERVICES
_CONFIG_LOADER = "apps/server/internal/config/config.go"
_REGISTRY = "ghcr.io/"
_SWITCH = re.compile(r'"(OPENPOST_[A-Z0-9_]*PRIVATE[A-Z0-9_]*)"')
_TIMEOUT_SECONDS = 30
_TRACKING_ISSUE = "https://github.com/infinito-nexus/core/issues/2867"


def private_network_switches(source: str) -> list[str]:
    """
    Args:
        source: Go source of OpenPost's config loader.

    Returns:
        The sorted, distinct ``OPENPOST_*PRIVATE*`` variables it names.
    """
    return sorted(set(_SWITCH.findall(source)))


def _pinned_config_loader_url() -> str:
    openpost = load_yaml_any(str(_SERVICES))["openpost"]
    repository = openpost["image"].removeprefix(_REGISTRY)
    return f"https://raw.githubusercontent.com/{repository}/{openpost['version']}/{_CONFIG_LOADER}"


class TestOpenPostNetguardAllowlist(unittest.TestCase):
    def test_the_detector_finds_a_private_network_switch(self) -> None:
        self.assertEqual(
            private_network_switches(
                'getEnvDefault("OPENPOST_ALLOWED_PRIVATE_CIDRS", "")\n'
                'getEnvDefault("OPENPOST_PRIVACY_URL", "")'
            ),
            ["OPENPOST_ALLOWED_PRIVATE_CIDRS"],
        )

    def test_the_pinned_openpost_offers_no_private_network_switch(self) -> None:
        url = _pinned_config_loader_url()
        try:
            response = requests.get(url, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            self._unverified(url, f"{type(exc).__name__}: {exc}")
        if response.status_code == 429 or response.status_code >= 500:
            self._unverified(url, f"HTTP {response.status_code}")
        self.assertEqual(
            response.status_code,
            200,
            f"{url} answered HTTP {response.status_code}; the pinned OpenPost no "
            "longer ships its config loader at this path",
        )
        switches = private_network_switches(response.text)
        self.assertEqual(
            switches,
            [],
            f"the pinned OpenPost reads {', '.join(switches)}, so netguard can "
            "allow private networks now; drop the relay workaround as described "
            f"in {_TRACKING_ISSUE}",
        )

    def _unverified(self, url: str, reason: str) -> None:
        warning(
            f"{url} was not checked ({reason})",
            title="OpenPost netguard pin unverified",
            file=str(_SERVICES.relative_to(PROJECT_ROOT)),
        )
        raise unittest.SkipTest(f"{url} unverified")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
