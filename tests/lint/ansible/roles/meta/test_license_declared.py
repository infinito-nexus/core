"""Lint guard: ``roles/<role>/meta/license.yml``.

Every invokable role names the licence of the software it deploys. The project
licence governs this repository's code and says nothing about the application a
role installs, which is where a restriction on commercial use usually sits: a
deployment cleared to use Infinito.Nexus commercially is still barred from
NLLB-200's weights.

The file carries ``spdx`` (one id, or ids joined by ``AND`` / ``OR``), ``url``
naming where the licence was read, and ``rights`` only for a grant
``meta/licenses.yml`` does not carry. A role that installs no software of its
own says so with ``# nocheck: license-declared <reason>`` in the file's head.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.licensing.rights import FIELDS, resolve
from utils.roles.mapping import ROLE_FILE_META_LICENSE
from utils.roles.required_by_coverage import role_is_invokable

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "license-declared"
_ALLOWED_KEYS = frozenset({"spdx", "url", "rights"})
_RIGHT_KEYS = frozenset((*FIELDS, "open_source"))


def _suppressed(path: Path) -> bool:
    """Whether the role opted out in the head of its licence file.

    Args:
        path: the role's ``meta/license.yml``.
    """
    if not path.is_file():
        return False
    return is_suppressed_in_head(read_text(str(path)).splitlines(), _RULE)


def _problems(role: str, path: Path) -> list[str]:
    """Return what is wrong with one role's licence file.

    Args:
        role: the role name, used in the message.
        path: the role's ``meta/license.yml``.
    """
    if not path.is_file():
        return [f"{role}: no meta/license.yml"]
    if _suppressed(path):
        return []

    parsed = load_yaml_any(str(path), default_if_missing={}) or {}
    if not isinstance(parsed, dict):
        return [f"{role}: meta/license.yml must be a mapping"]

    found: list[str] = []
    unknown = sorted(set(parsed) - _ALLOWED_KEYS)
    if unknown:
        found.append(f"{role}: non-allowlisted key(s) {unknown}")

    for field in ("spdx", "url"):
        value = parsed.get(field)
        if not isinstance(value, str) or not value.strip():
            found.append(f"{role}: `{field}` must be a non-empty string")

    inline = parsed.get("rights")
    if inline is not None:
        if not isinstance(inline, dict):
            found.append(f"{role}: `rights` must be a mapping")
        else:
            wrong = sorted(set(inline) ^ _RIGHT_KEYS)
            if wrong:
                found.append(
                    f"{role}: `rights` must hold exactly {sorted(_RIGHT_KEYS)}"
                )
            elif any(not isinstance(value, bool) for value in inline.values()):
                found.append(f"{role}: every `rights` value must be a bool")

    spdx = parsed.get("spdx")
    if (
        isinstance(spdx, str)
        and spdx.strip()
        and not found
        and resolve(spdx, inline if isinstance(inline, dict) else None) is None
    ):
        found.append(
            f"{role}: `{spdx}` names no entry in meta/licenses.yml and the "
            "role declares no inline `rights`"
        )

    return found


def offenders() -> list[str]:
    """Return every invokable role whose licence declaration is missing or wrong."""
    if not ROLES_DIR.is_dir():
        return []
    found: list[str] = []
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not role_dir.is_dir() or not role_is_invokable(role_dir.name):
            continue
        found.extend(_problems(role_dir.name, role_dir / ROLE_FILE_META_LICENSE))
    return found


class TestLicenseDeclared(unittest.TestCase):
    def test_every_invokable_role_names_its_software_licence(self) -> None:
        found = offenders()
        report = "\n".join(f"  - {problem}" for problem in found)
        self.assertFalse(
            found,
            f"{len(found)} problem(s) with the declared licence of the software "
            "these roles deploy, so the licence-context page cannot say whether "
            f"they may be used commercially:\n{report}\n\n"
            "Add meta/license.yml with `spdx` and the `url` you read it from, "
            "add the id to meta/licenses.yml or give the role inline `rights`, "
            f"or say why there is nothing to declare with `# nocheck: {_RULE} "
            "<reason>`.",
        )


if __name__ == "__main__":
    unittest.main()
