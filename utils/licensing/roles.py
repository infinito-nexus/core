"""A role's declared licence, resolved against the central table."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.licensing.rights import context_of, resolve
from utils.roles.mapping import ROLE_FILE_META_LICENSE

if TYPE_CHECKING:
    from pathlib import Path

    from utils.licensing.contexts import Context

RULE = "license-declared"
OWN_LICENSE = "LicenseRef-Infinito-Nexus-Community"


def deploys_nothing(role_dir: Path) -> bool:
    """Whether the role declares that it installs no third-party software.

    Args:
        role_dir: the role's directory.
    """
    path = role_dir / ROLE_FILE_META_LICENSE
    if not path.is_file():
        return False
    return is_suppressed_in_head(read_text(str(path)).splitlines(), RULE)


class Declared(NamedTuple):
    """What a role says about the licence of the software it deploys.

    Args:
        spdx: the SPDX expression, empty when the role declares none.
        url: where the licence was read.
        rights: the resolved rights row, None when no table entry matches.
        context: the class the generated page groups the role under.
    """

    spdx: str
    url: str
    rights: dict[str, bool] | None
    context: Context


def declared(role_dir: Path) -> Declared | None:
    """Return a role's licence, or None when it declares no licence file.

    Args:
        role_dir: the role's directory.
    """
    path = role_dir / ROLE_FILE_META_LICENSE
    if not path.is_file():
        return None
    parsed = load_yaml(str(path))
    if not isinstance(parsed, dict):
        return None
    spdx = str(parsed.get("spdx", "")).strip()
    inline = parsed.get("rights")
    rights = (
        resolve(spdx, inline if isinstance(inline, dict) else None) if spdx else None
    )
    return Declared(spdx, str(parsed.get("url", "")), rights, context_of(rights))
