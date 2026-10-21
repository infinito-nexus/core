"""Lint guard: an app-native OIDC consumer pins the provider it calls.

On an onion deployment the OIDC endpoints handed to an application are public
``.onion`` authorities. That is right for the browser, which reaches them
through Tor, and unroutable for the calls the application makes itself: the
code-to-token exchange, JWKS and userinfo all leave the container directly.
``lookup('container_extra_hosts')`` pins the provider to an address the
container can reach, sending those calls over the local network to the proxy
that already serves the vhost.

A role that consumes ``OIDC.CLIENT.ISSUER_URL`` therefore MUST emit that lookup
from one of its templates. Without it the deploy is green, the browser leg
works, and the first server-side call fails at runtime on an onion round only -
which is how ``web-app-jellyfin`` reached a release with the gap.

Out of scope is a role whose ``meta/services.yml`` declares
``sso.flavor: oauth2``: there the reverse proxy performs the exchange and the
application never calls the provider itself. So is a role that names the issuer
only in a Playwright env template, which hands it to the test harness rather
than to a container.

A role that genuinely makes no server-side call despite reading the issuer opts
out with ``# nocheck: sso-backchannel-pin`` naming the reason, anywhere in its
``meta/services.yml``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
_RULE = "sso-backchannel-pin"
_ISSUER = "OIDC.CLIENT.ISSUER_URL"
_PIN = "container_extra_hosts"


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        return load_yaml_str(text)
    except yaml.YAMLError:
        return None


def _suppressed(path: Path) -> bool:
    if not path.is_file():
        return False
    return any(line_has_rule(line, _RULE) for line in read_text(str(path)).splitlines())


def _contains(paths: list[Path], needle: str) -> bool:
    """Whether any readable file under *paths* holds *needle*.

    Args:
        paths: files to search.
        needle: the literal to look for.
    """
    for path in paths:
        if not path.is_file():
            continue
        try:
            if needle in read_text(str(path)):
                return True
        except UnicodeDecodeError:
            continue
    return False


def _proxy_gated(role_dir: Path) -> bool:
    """Whether the reverse proxy performs the exchange for this role.

    Args:
        role_dir: the role's directory.
    """
    services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
    sso = services.get("sso") if isinstance(services, dict) else None
    return isinstance(sso, dict) and sso.get("flavor") == "oauth2"


class TestSsoBackchannelPin(unittest.TestCase):
    def test_every_app_native_oidc_consumer_pins_the_provider(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            sources = [
                p
                for p in sorted(role_dir.glob("templates/**/*"))
                + sorted(role_dir.glob("vars/*.yml"))
                if "playwright" not in p.name
            ]
            if not _contains(sources, _ISSUER):
                continue
            if _proxy_gated(role_dir):
                continue
            if _suppressed(role_dir / ROLE_FILE_META_SERVICES):
                continue
            if _contains(sorted(role_dir.glob("templates/**/*")), _PIN):
                continue
            offenders.append(role_dir.name)

        if offenders:
            self.fail(
                f"Roles reading {_ISSUER} without pinning the provider "
                f"({len(offenders)}):\n"
                + "\n".join(f"  - {o}" for o in offenders)
                + "\n\nAdd to the service block of the compose template:\n"
                + f"  {{{{ lookup('{_PIN}') | indent(4) }}}}\n"
                + "\nThe lookup renders nothing where there is no onion to pin, so "
                "it is inert on clearnet.\n"
                + f"Or opt the role out with `# nocheck: {_RULE} — <reason>` in "
                + "meta/services.yml when it makes no server-side call."
            )


if __name__ == "__main__":
    unittest.main()
