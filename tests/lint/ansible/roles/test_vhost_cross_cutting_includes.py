"""Lint: a role-local vhost must carry the includes every vhost needs.

`sys-stk-front-proxy` renders a role's own ``templates/proxy.conf.j2`` when it
exists and one of the shared flavours otherwise. Overriding the file is how a
role expresses its own locations, and that is fine. What is not fine is that
overriding it silently drops every cross-cutting concern the shared flavours
carry, because those live as includes inside the file being replaced.

The MCP policy is the case that made this visible: it decides whether an
application's own vhost serves its declared endpoint path or returns 404, it was
added to both shared flavours, and the one provider whose native path most
needed hiding rendered from its own template and kept serving it.

The required set is derived from the shared flavours rather than listed here, so
a concern added to them is required of the overrides on the next run.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: vhost-cross-cutting-include`` in the head of the role's
  ``templates/proxy.conf.j2``, naming why the concern does not apply.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_SERVICES

_RULE = "vhost-cross-cutting-include"

FLAVOUR_DIR = PROJECT_ROOT / "roles/sys-svc-proxy/templates/vhost"
OVERRIDES = sorted((PROJECT_ROOT / "roles").glob("*/templates/proxy.conf.j2"))

_INCLUDE_RE = re.compile(r"""\{%-?\s*include\s+['"]([^'"]+)['"]""")

_LOCATION_SNIPPETS = "roles/sys-svc-proxy/templates/location/"


def flavour_includes() -> dict[str, set[str]]:
    """Return each shared flavour's include set, keyed by flavour name."""
    return {
        path.name: set(_INCLUDE_RE.findall(read_text(str(path))))
        for path in sorted(FLAVOUR_DIR.glob("*.conf.j2"))
    }


def required_includes() -> set[str]:
    """Return the includes every shared flavour carries.

    The intersection, not the union: a concern only one flavour needs is that
    flavour's business, while one both carry is what a vhost is expected to
    have regardless of shape. Location snippets are excluded because they are
    the part an override legitimately replaces.
    """
    sets = list(flavour_includes().values())
    if not sets:
        return set()
    common = set.intersection(*sets)
    return {inc for inc in common if not inc.startswith(_LOCATION_SNIPPETS)}


def role_of(path) -> str:
    """Return the role directory name of ``roles/<role>/templates/...``.

    Args:
        path: an absolute path under ``roles/``.
    """
    return path.relative_to(PROJECT_ROOT).parts[1]


def serves_mcp(role: str) -> bool:
    """Return whether a role declares an MCP endpoint path of its own.

    Args:
        role: the role directory name.
    """
    meta = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_MCP
    if not meta.is_file():
        return False
    block = load_yaml_any(str(meta), default_if_missing={})
    if not isinstance(block, Mapping):
        return False
    return bool((block.get("endpoint") or {}).get("path"))


def missing_includes() -> list[str]:
    """Return one finding per override dropping a concern that applies to it.

    An override is only asked for a concern its role actually has. The MCP
    policy renders nothing for a role with no endpoint path, so demanding it
    everywhere would report noise and train the reader to skip the report.
    """
    findings = []
    for path in OVERRIDES:
        if not serves_mcp(role_of(path)):
            continue
        content = read_text(str(path))
        if is_suppressed_in_head(content.splitlines(), _RULE):
            continue
        for missing in sorted(required_includes() - set(_INCLUDE_RE.findall(content))):
            rel = path.relative_to(PROJECT_ROOT)
            findings.append(f"{rel}: does not include {missing!r}")
    return findings


GATED_INCLUDES = (
    "roles/web-app-keycloak/templates/sso_proxy/endpoint.conf.j2",
    "roles/sys-svc-proxy/templates/headers/buffers.conf.j2",
)


def is_proxy_gated(role: str) -> bool:
    """Return whether oauth2-proxy fronts the role, per ``meta/services.yml``.

    Args:
        role: the role directory name.

    Mirrors ``utils.roles.applications.services.sso``: enabled and flavor
    ``oauth2``. An ``oidc`` role authenticates inside the application and its
    vhost carries no gate.
    """
    meta = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES
    if not meta.is_file():
        return False
    block = load_yaml_any(str(meta), default_if_missing={})
    sso = block.get("sso") if isinstance(block, Mapping) else None
    if not isinstance(sso, Mapping):
        return False
    return bool(sso.get("enabled")) and sso.get("flavor") == "oauth2"


def gated_without_the_gate() -> list[str]:
    """Return one finding per gated override missing a gate-only include.

    A gated vhost needs the oauth2-proxy endpoint to authenticate at all, and
    the raised header buffers because a Keycloak session cookie does not fit
    nginx's defaults. Neither is in the shared flavours' intersection, so the
    rule above cannot ask for them; an override that flips to ``oauth2`` later
    would drop both without a word.
    """
    findings = []
    for path in OVERRIDES:
        role = role_of(path)
        if not is_proxy_gated(role):
            continue
        content = read_text(str(path))
        if is_suppressed_in_head(content.splitlines(), _RULE):
            continue
        for missing in GATED_INCLUDES:
            if missing not in content:
                rel = path.relative_to(PROJECT_ROOT)
                findings.append(f"{rel}: is proxy-gated but omits {missing!r}")
    return findings


class TestVhostCrossCuttingIncludes(unittest.TestCase):
    def test_no_override_drops_a_shared_concern(self) -> None:
        findings = missing_includes()
        self.assertEqual(
            [],
            findings,
            f"role vhost(s) dropping a cross-cutting include ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_required_set_is_derived_and_not_empty(self) -> None:
        """An empty set would pass every override without checking anything."""
        self.assertTrue(
            required_includes(),
            "no include is common to the shared flavours, so the rule is vacuous",
        )

    def test_the_mcp_policy_is_required(self) -> None:
        """The concern this rule exists for must actually be in the set."""
        self.assertIn(
            "roles/sys-svc-proxy/templates/mcp/vhost.conf.j2", required_includes()
        )

    def test_the_overrides_are_found(self) -> None:
        self.assertTrue(OVERRIDES, "no role-local proxy.conf.j2 was scanned")

    def test_a_gated_override_carries_its_gate(self) -> None:
        findings = gated_without_the_gate()
        self.assertEqual(
            [],
            findings,
            f"proxy-gated vhost(s) missing a gate include ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_a_gated_override_is_actually_reached(self) -> None:
        """Without one in the set the gate rule would pass over nothing."""
        self.assertTrue(
            [role_of(p) for p in OVERRIDES if is_proxy_gated(role_of(p))],
            "no role both overrides its vhost and is fronted by oauth2-proxy",
        )

    def test_an_mcp_serving_override_is_actually_reached(self) -> None:
        """Most overrides serve no MCP, so the rule needs one that does."""
        reached = [role_of(p) for p in OVERRIDES if serves_mcp(role_of(p))]
        self.assertTrue(
            reached, "no role both overrides its vhost and declares an MCP endpoint"
        )

    def test_location_snippets_are_not_required(self) -> None:
        """Locations are what an override exists to replace."""
        self.assertFalse(
            [inc for inc in required_includes() if inc.startswith(_LOCATION_SNIPPETS)]
        )


if __name__ == "__main__":
    unittest.main()
