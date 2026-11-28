"""Lint guard: an app-native OIDC consumer pins the provider it calls.

On an onion deployment the OIDC endpoints handed to an application are public
``.onion`` authorities. That is right for the browser, which reaches them
through Tor, and unroutable for the calls the application makes itself: the
discovery fetch, the code-to-token exchange, JWKS and userinfo all leave the
container directly. ``lookup('container_extra_hosts')`` pins the provider to an
address the container can reach, sending those calls over the local network to
the proxy that already serves the vhost.

A role that hands a container one of the endpoints only a server calls -
``OIDC.CLIENT.ISSUER_URL``, ``DISCOVERY_DOCUMENT``, ``TOKEN_URL``,
``USER_INFO_URL`` or ``CERTS`` - from its templates, vars, meta or tasks
therefore MUST emit that lookup from one of its templates. Without it the deploy
is green, the browser leg works, and the first server-side call fails at runtime
on an onion round only - which is how ``web-app-jellyfin`` reached a release
with the gap, and why ``web-app-matomo``, whose endpoints sit in
``meta/services.yml``, answered every onion callback with a 500.
``AUTHORIZE_URL``, ``LOGOUT_URL`` and the account URLs are browser redirects and
out of scope.

The plain lookup pins the provider only when the role's own ``services.sso`` is
enabled. A role that declares no ``sso`` service, such as ``svc-ai-litellm``
serving the UI of ``web-app-litellm``, MUST name what it calls with
``onion_peers=`` (or borrow a gate with ``application_id=``); a bare lookup
there renders nothing and counts as no pin.

Out of scope is a role whose ``meta/services.yml`` declares
``sso.flavor: oauth2``: there the reverse proxy performs the exchange and the
application never calls the provider itself. So is a file named after
Playwright, which hands the endpoint to the test harness rather than to a
container.

A role that genuinely makes no server-side call despite reading such an
endpoint, e.g. a task that only probes it from the controller, opts out with
``# nocheck: sso-backchannel-pin`` naming the reason, anywhere in its
``meta/services.yml``.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
_RULE = "sso-backchannel-pin"
_SERVER_SIDE = re.compile(
    r"\bOIDC\.CLIENT\.(?:ISSUER_URL|DISCOVERY_DOCUMENT|TOKEN_URL|USER_INFO_URL|CERTS)\b"
)
_SOURCES = ("templates/**/*", "vars/*.yml", "meta/**/*.yml", "tasks/**/*.yml")
_PIN = "container_extra_hosts"
_PIN_CALL = re.compile(rf"{_PIN}(.*?)(?:\}}\}}|%\}})", re.DOTALL)
_PEER_ARGS = ("onion_peers=", "application_id=")


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return read_text(str(path))
    except UnicodeDecodeError:
        return ""


def _load_yaml(path: Path) -> Any:
    text = _read(path)
    if not text.strip():
        return None
    try:
        return load_yaml_str(text)
    except yaml.YAMLError:
        return None


def _suppressed(path: Path) -> bool:
    return any(line_has_rule(line, _RULE) for line in _read(path).splitlines())


def _reads_server_side_endpoint(role_dir: Path) -> bool:
    """Whether a non-Playwright source of the role names a server-side endpoint.

    Args:
        role_dir: the role's directory.
    """
    return any(
        _SERVER_SIDE.search(_read(path))
        for pattern in _SOURCES
        for path in sorted(role_dir.glob(pattern))
        if "playwright" not in path.name
    )


def _pin_calls(role_dir: Path) -> list[str]:
    """The argument text of every pin lookup in the role's templates.

    Args:
        role_dir: the role's directory.
    """
    return [
        match.group(1)
        for path in sorted(role_dir.glob("templates/**/*"))
        for match in _PIN_CALL.finditer(_read(path))
    ]


def offenders(roles_dir: Path) -> list[str]:
    """Args:
        roles_dir: the ``roles`` directory to scan.

    Returns:
        One line per role that hands a container a server-side OIDC endpoint
        without a pin that reaches the provider.
    """
    found: list[str] = []
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        if not _reads_server_side_endpoint(role_dir):
            continue
        services_file = role_dir / ROLE_FILE_META_SERVICES
        services = _load_yaml(services_file)
        sso = services.get("sso") if isinstance(services, dict) else None
        if isinstance(sso, dict) and sso.get("flavor") == "oauth2":
            continue
        if _suppressed(services_file):
            continue
        calls = _pin_calls(role_dir)
        if not calls:
            found.append(f"{role_dir.name}: no {_PIN} lookup in its templates")
        elif not isinstance(sso, dict) and not any(
            arg in call for call in calls for arg in _PEER_ARGS
        ):
            found.append(
                f"{role_dir.name}: declares no sso service, so a bare {_PIN} "
                "lookup pins nothing; pass onion_peers= with the endpoints it calls"
            )
    return found


class TestSsoBackchannelPin(unittest.TestCase):
    def test_every_app_native_oidc_consumer_pins_the_provider(self) -> None:  # nocheck: test.text-presence -- policy lint over every OIDC consumer role  # fmt: skip
        found = offenders(ROLES_DIR)
        self.assertEqual(
            [],
            found,
            f"Roles calling the OIDC provider server-side without a pin "
            f"({len(found)}):\n"
            + "\n".join(f"  - {line}" for line in found)
            + "\n\nAdd to the service block of the compose template:\n"
            + f"  {{{{ lookup('{_PIN}') | indent(4) }}}}\n"
            + "or, for a role without an sso service:\n"
            + f"  {{{{ lookup('{_PIN}', onion_peers=[OIDC.CLIENT.TOKEN_URL]) | indent(4) }}}}\n"
            + "\nThe lookup renders nothing where there is no onion to pin, so "
            "it is inert on clearnet.\n"
            + f"Or opt the role out with `# nocheck: {_RULE}  <reason>` in "
            + "meta/services.yml when it makes no server-side call.",
        )

    def test_the_scan_flags_each_unpinned_shape_and_spares_the_rest(self) -> None:
        oidc = "sso:\n  enabled: true\n  flavor: oidc\n"
        fixtures = {
            "web-app-token": {
                ROLE_FILE_META_SERVICES: oidc,
                "templates/env.j2": "TOKEN={{ OIDC.CLIENT.TOKEN_URL }}\n",
            },
            "web-app-meta": {
                ROLE_FILE_META_SERVICES: oidc
                + "app:\n  oidc:\n    user_info_url: '{{ OIDC.CLIENT.USER_INFO_URL }}'\n",
            },
            "web-app-task": {
                ROLE_FILE_META_SERVICES: oidc,
                "tasks/oidc.yml": "- x:\n    url: '{{ OIDC.CLIENT.DISCOVERY_DOCUMENT }}'\n",
            },
            "svc-ai-bare": {
                "templates/env.j2": "JWKS={{ OIDC.CLIENT.CERTS }}\n",
                ROLE_FILE_TEMPL_COMPOSE: "    {{ lookup('container_extra_hosts') | indent(4) }}\n",
            },
            "svc-ai-peered": {
                "templates/env.j2": "TOKEN={{ OIDC.CLIENT.TOKEN_URL }}\n",
                ROLE_FILE_TEMPL_COMPOSE: "    {{ lookup('container_extra_hosts',\n"
                "        onion_peers=[OIDC.CLIENT.TOKEN_URL]) | indent(4) }}\n",
            },
            "web-app-pinned": {
                ROLE_FILE_META_SERVICES: oidc,
                ROLE_FILE_VARS_MAIN: "ISSUER: '{{ OIDC.CLIENT.ISSUER_URL }}'\n",
                ROLE_FILE_TEMPL_COMPOSE: "    {{ lookup('container_extra_hosts') | indent(4) }}\n",
            },
            "web-app-proxied": {
                ROLE_FILE_META_SERVICES: "sso:\n  enabled: true\n  flavor: oauth2\n",
                "templates/env.j2": "TOKEN={{ OIDC.CLIENT.TOKEN_URL }}\n",
            },
            "web-app-harness": {
                ROLE_FILE_META_SERVICES: oidc,
                "templates/playwright.env.j2": "ISSUER={{ OIDC.CLIENT.ISSUER_URL }}\n",
            },
            "web-app-browser": {
                ROLE_FILE_META_SERVICES: oidc,
                "templates/env.j2": "AUTH={{ OIDC.CLIENT.AUTHORIZE_URL }}\n"
                "OUT={{ OIDC.CLIENT.LOGOUT_URL }}\n",
            },
            "web-app-optout": {
                ROLE_FILE_META_SERVICES: f"# nocheck: {_RULE}  controller-side probe only\n"
                + oidc,
                "tasks/probe.yml": "- x:\n    url: '{{ OIDC.CLIENT.TOKEN_URL }}'\n",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            for role, files in fixtures.items():
                for rel, body in files.items():
                    target = roles_dir / role / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(body, encoding="utf-8")
            flagged = [line.split(":", 1)[0] for line in offenders(roles_dir)]

        self.assertEqual(
            flagged, ["svc-ai-bare", "web-app-meta", "web-app-task", "web-app-token"]
        )


if __name__ == "__main__":
    unittest.main()
