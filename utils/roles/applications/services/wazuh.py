from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from pathlib import Path

RULE_BLOCK_MIN = 101000
RULE_BLOCK_MAX = 118999
RULE_BLOCK_SIZE = 100
BASE_RULE_MIN = 100100
BASE_RULE_MAX = 100999
SELFTEST_TAG = "infinito-selftest"
PROVIDER_ENTITY = "wazuh"
SAMPLES_FILE = "samples.yml"


def decoder_name(entity: str) -> str:
    """Return the base parent decoder name of an app tag.

    Args:
        entity: the role's entity name, which is its journald tag.
    """
    return f"infinito-{entity}"


def load_samples(path: Path) -> list[dict[str, Any]]:
    """Return a role's samples with ``log`` normalised to a list of lines.

    Args:
        path: the role's ``files/wazuh/samples.yml``; absent means no samples.

    Returns:
        ``[{lines, rule, level}]`` in file order.
    """
    samples = load_yaml_any(str(path), default_if_missing=[]) or []
    return [
        {
            "lines": [sample["log"]] if isinstance(sample["log"], str) else list(sample["log"]),
            "rule": sample["rule"],
            "level": sample["level"],
        }
        for sample in samples
    ]


def _parse(path: Path) -> ET.Element:
    # Exception: Wazuh rule files hold several top-level elements, which plain XML rejects.
    return ET.fromstring(f"<root>{read_text(str(path))}</root>")


def _ids(value: str | None) -> list[int]:
    return [int(part) for part in re.split(r"[,\s]+", value or "") if part]


def _is_correlation(rule: ET.Element) -> bool:
    return (
        rule.get("frequency") is not None
        or rule.find("if_matched_sid") is not None
        or rule.find("if_matched_group") is not None
    )


def _file_errors(
    role: str, entity: str, start: int, wazuh_dir: Path
) -> tuple[list[str], dict[int, bool]]:
    errors: list[str] = []
    correlation: dict[int, bool] = {}
    block = range(start, start + RULE_BLOCK_SIZE)
    rules_path = wazuh_dir / "rules.xml"
    if rules_path.is_file():
        try:
            rules = list(_parse(rules_path).iter("rule"))
        except ET.ParseError as exc:
            return [f"{rules_path}: not parseable: {exc}"], correlation
        for rule in rules:
            rule_id = int(rule.get("id", "0"))
            if rule_id in correlation:
                errors.append(f"{role}: rule id {rule_id} is defined twice")
            correlation[rule_id] = _is_correlation(rule)
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
            return [*errors, f"{decoders_path}: not parseable: {exc}"], correlation
        errors.extend(
            f"{role}: decoder '{decoder.get('name')}' needs <parent>{decoder_name(entity)}</parent>"
            for decoder in decoders
            if (decoder.findtext("parent") or "").strip() != decoder_name(entity)
        )
    return errors, correlation


def _single_line(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != "" and "\n" not in value and "\r" not in value


def _sample_errors(
    role: str, wazuh_dir: Path, allowed: range, correlation: dict[int, bool]
) -> list[str]:
    path = wazuh_dir / SAMPLES_FILE
    samples = load_yaml_any(str(path), default_if_missing=[]) or []
    if not isinstance(samples, list):
        return [f"{path}: must be a list of {{log, rule, level}}"]
    errors: list[str] = []
    covered: set[int] = set()
    for index, sample in enumerate(samples):
        where = f"{role}: sample {index + 1}"
        if not isinstance(sample, dict) or set(sample) != {"log", "rule", "level"}:
            errors.append(f"{where}: needs exactly the keys log, rule, level")
            continue
        rule, level, log = sample["rule"], sample["level"], sample["log"]
        if not isinstance(level, int) or isinstance(level, bool):
            errors.append(f"{where}: level must be an integer")
        if not isinstance(rule, int) or isinstance(rule, bool) or rule not in allowed:
            errors.append(f"{where}: rule {rule} is outside {allowed[0]}-{allowed[-1]}")
            continue
        covered.add(rule)
        if isinstance(log, list):
            if len(log) < 2:
                errors.append(f"{where}: a log list needs at least 2 lines")
            if not correlation.get(rule, False):
                errors.append(
                    f"{where}: a log list is only allowed for a correlation rule "
                    "(frequency, if_matched_sid, if_matched_group)"
                )
            if not all(_single_line(line) for line in log):
                errors.append(f"{where}: every log line must be a single non-empty line")
        elif not _single_line(log):
            errors.append(f"{where}: log must be a single non-empty line or a list of them")
    errors.extend(
        f"{role}: rule {rule_id} has no sample"
        for rule_id in sorted(set(correlation) - covered)
    )
    return errors


def rule_block_errors(applications: dict[str, Any], roles_dir: Path) -> list[str]:
    """Check every role's Wazuh rule block, rule files and samples.

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
        wazuh_dir = roles_dir / role / "files" / "wazuh"
        if entity == PROVIDER_ENTITY:
            errors.extend(
                _sample_errors(role, wazuh_dir, range(BASE_RULE_MIN, BASE_RULE_MAX + 1), {})
            )
            continue
        if entity == SELFTEST_TAG:
            errors.append(f"{role}: entity name '{SELFTEST_TAG}' is reserved")
        services = applications[role].get("services") or {}
        wazuh = services.get("wazuh") if isinstance(services, dict) else None
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
        file_errors, correlation = _file_errors(role, entity, start, wazuh_dir)
        errors.extend(file_errors)
        errors.extend(
            _sample_errors(role, wazuh_dir, range(start, start + RULE_BLOCK_SIZE), correlation)
        )
    blocks.sort()
    errors.extend(
        f"{role} and {next_role}: rule blocks {start} and {next_start} overlap"
        for (start, role), (next_start, next_role) in zip(blocks, blocks[1:])
        if next_start < start + RULE_BLOCK_SIZE
    )
    return errors
