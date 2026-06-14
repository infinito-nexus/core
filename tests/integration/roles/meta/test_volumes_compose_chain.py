"""Compose <-> volumes chain.

For every role that ships `templates/compose.yml.j2` and uses one or more
named volumes there, this test enforces a four-step contract per used
volume so the deployment is swarm + NFS portable:

1. The volume short-name MUST be declared as a top-level key in
   `meta/volumes.yml` (dict-of-dicts canonical shape).
2. The declared entry MUST be a `type: volume` mapping (bind / config /
   secret / tmpfs entries cannot be docker named volumes).
3. `vars/main.yml` MUST expose an UPPERCASE constant whose value reads
   `lookup('config', application_id, 'volumes.<key>.name')` or the
   equivalent `lookup('volume', application_id, '<key>').name` form.
4. That constant MUST be referenced from `templates/compose.yml.j2`.

A literal volume name in the compose template silently bypasses
`compose_volumes`' NFS rewriting and breaks swarm deploys; the chain
forces the value to flow through the role's vars indirection.
"""

import re
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

CONST_NAME_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*:")
LOOKUP_VOLUME_RE = re.compile(
    r"""lookup\(\s*['"]config['"]\s*,\s*[^,]+,\s*['"]volumes\.(?P<cfg_key>[A-Za-z0-9_\-]+)\.(?:name|path)['"]"""
    r"""|"""
    r"""lookup\(\s*['"]volume['"]\s*,\s*[^,]+,\s*['"](?P<vol_key>[A-Za-z0-9_\-]+)['"]\s*\)\s*\.\s*(?:name|path)"""
)
EXTRA_VOLUMES_KEY_RE = re.compile(
    r"""extra_volumes\s*=\s*\{(?P<body>(?:[^{}]|\{[^{}]*\})*)\}""",
    re.DOTALL,
)
DICT_KEY_RE = re.compile(r"""['"]([A-Za-z][A-Za-z0-9_\-]*)['"]\s*:\s*\{""")
MOUNT_LINE_RE = re.compile(
    r"""^\s*-\s*['"]?(?P<vol>[A-Za-z][A-Za-z0-9_\-]*)\s*:\s*/(?!/)""",
    re.MULTILINE,
)


def _roles_with_compose() -> list[Path]:
    roles_dir = PROJECT_ROOT / "roles"
    return [
        role_dir
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir())
        if (role_dir / ROLE_FILE_TEMPL_COMPOSE).is_file()
    ]


def _volume_short_names_used_in_compose(compose_text: str) -> set[str]:
    names: set[str] = set()
    for m in EXTRA_VOLUMES_KEY_RE.finditer(compose_text):
        for km in DICT_KEY_RE.finditer(m.group("body")):
            names.add(km.group(1))
    for m in MOUNT_LINE_RE.finditer(compose_text):
        names.add(m.group("vol"))
    return names


def _constants_referencing_volume(vars_text: str, volume_key: str) -> list[str]:
    constants: list[str] = []
    current_const: str | None = None
    pending_value_lines: list[str] = []
    for raw in vars_text.splitlines():
        match = CONST_NAME_RE.match(raw)
        if match:
            if current_const is not None and _block_references(
                volume_key, pending_value_lines
            ):
                constants.append(current_const)
            current_const = match.group(1)
            pending_value_lines = [raw[match.end() :]]
        elif current_const is not None:
            pending_value_lines.append(raw)
    if current_const is not None and _block_references(volume_key, pending_value_lines):
        constants.append(current_const)
    return constants


def _block_references(volume_key: str, lines: list[str]) -> bool:
    body = "\n".join(lines)
    for match in LOOKUP_VOLUME_RE.finditer(body):
        matched_key = match.group("cfg_key") or match.group("vol_key")
        if matched_key == volume_key:
            return True
    return False


class TestVolumesComposeChain(unittest.TestCase):
    def test_every_compose_volume_flows_through_role_vars_constant(self):
        offenders: list[str] = []
        for role_dir in _roles_with_compose():
            role_name = role_dir.name
            compose_text = read_text(str(role_dir / ROLE_FILE_TEMPL_COMPOSE))
            volume_keys = _volume_short_names_used_in_compose(compose_text)
            if not volume_keys:
                continue

            volumes_yml = role_dir / ROLE_FILE_META_VOLUMES
            vars_yml = role_dir / ROLE_FILE_VARS_MAIN
            volumes_data: dict = {}
            if volumes_yml.is_file():
                loaded = load_yaml_any(str(volumes_yml)) or {}
                if isinstance(loaded, dict):
                    volumes_data = loaded
            vars_text = read_text(str(vars_yml)) if vars_yml.is_file() else ""

            for volume_key in sorted(volume_keys):
                entry = volumes_data.get(volume_key)
                if not isinstance(entry, dict):
                    offenders.append(
                        f"{role_name}: compose.yml.j2 uses named volume "
                        f"'{volume_key}' but it is not declared in "
                        f"meta/volumes.yml"
                    )
                    continue
                if entry.get("type", "volume") != "volume":
                    offenders.append(
                        f"{role_name}: compose.yml.j2 uses named volume "
                        f"'{volume_key}' but meta/volumes.yml entry has "
                        f"type={entry.get('type')!r} (only type: volume "
                        f"entries can be docker named volumes)"
                    )
                    continue
                constants = _constants_referencing_volume(vars_text, volume_key)
                if not constants:
                    offenders.append(
                        f"{role_name}: compose.yml.j2 uses named volume "
                        f"'{volume_key}' but no UPPERCASE constant in "
                        f"vars/main.yml reads "
                        f"lookup('config', ..., 'volumes.{volume_key}.name') "
                        f"or lookup('volume', ..., '{volume_key}').name"
                    )
                    continue
                used = [
                    c
                    for c in constants
                    if re.search(rf"\b{re.escape(c)}\b", compose_text)
                ]
                if not used:
                    offenders.append(
                        f"{role_name}: vars/main.yml declares constant(s) "
                        f"{constants} for volume '{volume_key}' but none "
                        f"of them is referenced from templates/compose.yml.j2"
                    )
        if offenders:
            self.fail(
                "Compose volume chain violations (each named volume used "
                "in templates/compose.yml.j2 MUST be declared in "
                "meta/volumes.yml, exposed as an UPPERCASE constant in "
                "vars/main.yml, and referenced via that constant so "
                "swarm + NFS rewriting cannot be bypassed):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
