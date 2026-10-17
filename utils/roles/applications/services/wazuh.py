from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from pathlib import Path

RULE_BLOCK_MIN = 101000
RULE_BLOCK_MAX = 118999
RULE_BLOCK_SIZE = 100
SELFTEST_TAG = "infinito-selftest"
PROVIDER_ENTITY = "wazuh"


def decoder_name(entity: str) -> str:
    """Return the base parent decoder name of an app tag.

    Args:
        entity: the role's entity name, which is its journald tag.
    """
    return f"infinito-{entity}"


def _parse(path: Path) -> ET.Element:
    # Exception: Wazuh rule files hold several top-level elements, which plain XML rejects.
    return ET.fromstring(f"<root>{read_text(str(path))}</root>")


def _ids(value: str | None) -> list[int]:
    return [int(part) for part in re.split(r"[,\s]+", value or "") if part]


def _file_errors(role: str, entity: str, start: int, wazuh_dir: Path) -> list[str]:
    errors: list[str] = []
    block = range(start, start + RULE_BLOCK_SIZE)
    rules_path = wazuh_dir / "rules.xml"
    if rules_path.is_file():
        try:
            rules = _parse(rules_path).iter("rule")
        except ET.ParseError as exc:
            return [f"{rules_path}: not parseable: {exc}"]
        seen: set[int] = set()
        for rule in rules:
            rule_id = int(rule.get("id", "0"))
            if rule_id in seen:
                errors.append(f"{role}: rule id {rule_id} is defined twice")
            seen.add(rule_id)
            if rule_id == start or rule_id not in block:
                errors.append(
                    f"{role}: rule id {rule_id} is outside {start + 1}-{block[-1]}; "
                    f"{start} is the central parent rule"
                )
            parents = _ids(rule.findtext("if_sid")) + _ids(
                rule.findtext("if_matched_sid")
            )
            if not parents:
                errors.append(
                    f"{role}: rule {rule_id} has no if_sid or if_matched_sid, "
                    f"so it is not scoped on the {entity} tag"
                )
            errors.extend(
                f"{role}: rule {rule_id} chains to {parent} outside its block {start}-{block[-1]}"
                for parent in parents
                if parent not in block
            )
    decoders_path = wazuh_dir / "decoders.xml"
    if decoders_path.is_file():
        try:
            decoders = _parse(decoders_path).iter("decoder")
        except ET.ParseError as exc:
            return [*errors, f"{decoders_path}: not parseable: {exc}"]
        errors.extend(
            f"{role}: decoder '{decoder.get('name')}' needs <parent>{decoder_name(entity)}</parent>"
            for decoder in decoders
            if (decoder.findtext("parent") or "").strip() != decoder_name(entity)
        )
    return errors


def rule_block_errors(applications: dict[str, Any], roles_dir: Path) -> list[str]:
    """Check every role's Wazuh rule block and rule files.

    Args:
        applications: role id to merged application defaults.
        roles_dir: the directory holding ``<role>/files/wazuh``.

    Returns:
        One message per violation, empty when everything is consistent.
    """
    errors: list[str] = []
    blocks: list[tuple[int, str]] = []
    for role in sorted(applications):
        entity = get_entity_name(role)
        if entity == PROVIDER_ENTITY:
            continue
        if entity == SELFTEST_TAG:
            errors.append(f"{role}: entity name '{SELFTEST_TAG}' is reserved")
        services = applications[role].get("services") or {}
        wazuh = services.get("wazuh") if isinstance(services, dict) else None
        wazuh_dir = roles_dir / role / "files" / "wazuh"
        opted_in = isinstance(wazuh, dict) and "enabled" in wazuh
        start = wazuh.get("rule_block") if isinstance(wazuh, dict) else None
        if start is None:
            if opted_in or (wazuh_dir / "rules.xml").is_file():
                errors.append(
                    f"{role}: declares Wazuh rules or opts in, but sets no services.wazuh.rule_block"
                )
            continue
        if not isinstance(start, int) or isinstance(start, bool):
            errors.append(f"{role}: services.wazuh.rule_block must be an integer")
            continue
        if start < RULE_BLOCK_MIN or start + RULE_BLOCK_SIZE - 1 > RULE_BLOCK_MAX:
            errors.append(
                f"{role}: rule block {start}-{start + RULE_BLOCK_SIZE - 1} is outside "
                f"{RULE_BLOCK_MIN}-{RULE_BLOCK_MAX}"
            )
        blocks.append((start, role))
        errors.extend(_file_errors(role, entity, start, wazuh_dir))
    blocks.sort()
    errors.extend(
        f"{role} and {next_role}: rule blocks {start} and {next_start} overlap"
        for (start, role), (next_start, next_role) in zip(blocks, blocks[1:])
        if next_start < start + RULE_BLOCK_SIZE
    )
    return errors
