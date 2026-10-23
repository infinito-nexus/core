"""Lint guard: a variant binding a clearnet-only role must not pin the onion on.

A role whose ``meta/services.yml`` pins ``tor.enabled`` to a literal false rides
no node onion, so on a tor deployment its surface lives at a clearnet host that
no onion browser reaches, and the dashboard's own
``frame-src 'self' http://*.<onion>`` forbids embedding it. A variant that
enables such a role and pins ``services.tor.enabled: true`` therefore declares a
combination the deployment cannot hold: the round advertises a tile, a tracker,
a stylesheet and a scrape target for a surface that is not there.

``test_sso_variant_requires_tor`` states the complementary half - every variant
of a role that has an onion MUST pin it on - and exempts the clearnet-only role
itself. This rule covers the consumers it does not: the variants that bind one.

The project already applies the rule by hand. ``web-app-nextcloud``'s variants
head carries "variant 8 pairs PeerTube, which is clearnet-only since 8ffb1f567,
so that round cannot pin the onion on".

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: clearnet-variant-tor`` in the CLEARNET role's
  ``meta/services.yml``, which exempts it everywhere: a relay with no browser
  surface of its own carries no tile and no injected asset, so an onion round
  may deploy it without claiming anything about it.
* the same marker in a consumer's ``meta/variants.yml`` for a case that is
  sound only there.

The marker belongs on the bound role rather than the consumer whenever the
reason is the role's own shape, because a consumer-side marker would also
silence the pairings of every other clearnet role in the same file.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
_RULE = "clearnet-variant-tor"


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


def _suppressed(paths: tuple[Path, ...]) -> bool:
    for path in paths:
        if not path.is_file():
            continue
        if any(
            line_has_rule(line, _RULE) for line in read_text(str(path)).splitlines()
        ):
            return True
    return False


def _flag(variant: Any, service: str) -> Any:
    services = variant.get("services") if isinstance(variant, dict) else None
    entry = services.get(service) if isinstance(services, dict) else None
    return entry.get("enabled") if isinstance(entry, dict) else None


def clearnet_only_keys() -> dict[str, str]:
    """Service key to role id, for every clearnet-only role the rule covers.

    Returns:
        The key a consumer's variant would bind it under, mapped to the role
        that declares itself clearnet-only. A role carrying the marker in its
        own ``meta/services.yml`` is left out, so it is exempt everywhere.
    """
    found: dict[str, str] = {}
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        services_path = role_dir / ROLE_FILE_META_SERVICES
        services = _load_yaml(services_path)
        tor = services.get("tor") if isinstance(services, dict) else None
        if not isinstance(tor, dict) or tor.get("enabled") is not False:
            continue
        if _suppressed((services_path,)):
            continue
        key = entity_name(role_dir.name)
        if key:
            found[key] = role_dir.name
    return found


class TestClearnetRoleForbidsVariantTor(unittest.TestCase):
    def test_no_variant_pins_the_onion_while_binding_a_clearnet_role(self) -> None:
        clearnet = clearnet_only_keys()
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants = _load_yaml(variants_path)
            if not isinstance(variants, list) or not variants:
                continue
            if _suppressed((variants_path,)):
                continue

            for index, variant in enumerate(variants):
                if _flag(variant, "tor") is not True:
                    continue
                for key, bound_role in sorted(clearnet.items()):
                    if _flag(variant, key) is True:
                        offenders.append(
                            f"{role_dir.name} variant {index}: pins "
                            f"services.tor.enabled true while enabling {key!r} "
                            f"({bound_role}), which pins tor.enabled false"
                        )

        self.assertEqual(
            offenders,
            [],
            "A variant may not pin the onion on while binding a role that rides "
            "none; that round advertises a surface no onion browser can reach. "
            f"Turn tor off for the variant, or suppress with '# nocheck: {_RULE}' "
            "naming why the pairing is sound:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
