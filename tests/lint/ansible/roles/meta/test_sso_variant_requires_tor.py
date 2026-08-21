"""Lint guard: the variant-level tor contract.

Two rules, both opting out through ``# nocheck: sso-variant-tor``.

The second: every variant of a role that declares a ``tor:`` block MUST pin
``services.tor.enabled: true``. The onion is the shape the platform breaks in -
plaintext origins drop ``Secure`` cookies, an https identity provider cannot
embed in an http page, ``crypto.subtle`` is undefined outside a secure context -
so a variant that never runs it is not testing the deployment users get.

No variant is exempt, not even the minimal round: the onion is part of the
deployment under test, not a feature bolted onto the full shape. Roles without a
tor block are out of scope - they have no onion to pin, and ``test_tor_contract``
already decides who needs the block; so is a role whose ``meta/services.yml``
pins ``tor.enabled`` to a literal false, which has already declared it has none.

The first: a variant that turns SSO on must also turn the onion on.

Single sign-on over a plaintext ``http://<onion>`` origin is where the platform
breaks in ways clearnet never shows: a framework's ``Secure`` session-cookie
default silently drops the cookie, an https identity provider cannot be embedded
in an http page, and ``crypto.subtle`` is undefined because an onion is not a
secure context. None of that surfaces unless a variant deploys SSO and the onion
together, so every ``meta/variants.yml`` entry pinning
``services.sso.enabled: true`` MUST also pin ``services.tor.enabled: true``.

A role that genuinely cannot serve SSO over the onion opts out with
``# nocheck: sso-variant-tor`` anywhere in its ``meta/variants.yml`` or
``meta/services.yml``, naming the reason. Three kinds qualify: a role whose
``meta/services.yml`` pins ``tor.enabled`` to a literal false (it has no onion at
all), a role whose SSO gate is itself disabled on a tor node, and a role whose
login flow needs a browser API that a non-secure context withholds.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
_RULE = "sso-variant-tor"


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


def _declares_tor(role_dir: Path) -> bool:
    """True iff the role has an onion a variant could pin on.

    Args:
        role_dir: the role's directory.

    A ``meta/services.yml`` that pins ``tor.enabled`` to a literal false has
    already declared the role has no onion at all - the first of the three
    opt-out cases - so it needs no marker repeating that in a comment.
    """
    services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
    tor = services.get("tor") if isinstance(services, dict) else None
    return isinstance(tor, dict) and tor.get("enabled") is not False


class TestSsoVariantRequiresTor(unittest.TestCase):
    def test_every_sso_variant_pins_the_onion_on(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants = _load_yaml(variants_path)
            if not isinstance(variants, list) or not variants:
                continue
            if _suppressed((variants_path, role_dir / ROLE_FILE_META_SERVICES)):
                continue

            for index, variant in enumerate(variants):
                if _flag(variant, "sso") is not True:
                    continue
                tor = _flag(variant, "tor")
                if tor is True:
                    continue
                offenders.append(
                    f"{role_dir.name}: variant {index} pins services.sso.enabled "
                    f"true but services.tor.enabled is {tor!r} — SSO must be "
                    f"exercised over the onion, where it actually breaks."
                )

        if offenders:
            self.fail(
                f"Variants enabling SSO without the onion ({len(offenders)}):\n"
                + "\n".join(f"  - {o}" for o in offenders)
                + "\n\nAdd to the variant's services block:\n"
                + "  tor:\n"
                + "    enabled: true\n"
                + f"\nOr opt the role out with `# nocheck: {_RULE} — <reason>` in "
                + "meta/variants.yml when it cannot serve SSO over an onion."
            )

    def test_every_variant_pins_the_onion_on(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants = _load_yaml(variants_path)
            if not isinstance(variants, list) or not variants:
                continue
            if not _declares_tor(role_dir):
                continue
            if _suppressed((variants_path, role_dir / ROLE_FILE_META_SERVICES)):
                continue

            for index, variant in enumerate(variants):
                tor = _flag(variant, "tor")
                if tor is True:
                    continue
                offenders.append(
                    f"{role_dir.name}: variant {index} has services.tor.enabled {tor!r}"
                )

        if offenders:
            self.fail(
                f"Variants not pinning the onion on ({len(offenders)}):\n"
                + "\n".join(f"  - {o}" for o in offenders)
                + "\n\nThe onion is the shape the platform breaks in, so every "
                "variant of a role that declares a tor block exercises it "
                "unless the role states why it cannot:\n"
                + "  tor:\n"
                + "    enabled: true\n"
                + f"\nOr opt the role out with `# nocheck: {_RULE} — <reason>`."
            )


if __name__ == "__main__":
    unittest.main()
