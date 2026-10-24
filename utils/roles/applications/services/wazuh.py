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
# Exception: the top IDs of every app block hold the central Docker attribution rules; compose and swarm label the project differently, a health-check exec needs its own level-0 child and an OOM kill its own higher-level child.
DOCKER_RULE_OFFSETS = {"oom": 96, "healthcheck": 97, "swarm": 98, "compose": 99}
APP_RULE_LIMIT = min(DOCKER_RULE_OFFSETS.values())
BASE_RULE_MIN = 100100
BASE_RULE_MAX = 100999
SELFTEST_TAG = "infinito-selftest"
DEPLOY_TAG = "infinito-deploy"
FIM_TAG = "infinito-fim"
WATCH_TAG = "infinito-wazuh-watch"
OWN_TAGS = (SELFTEST_TAG, DEPLOY_TAG, FIM_TAG, WATCH_TAG)
JOURNALD_PROGRAM = "systemd-journald"
# Exception: Wazuh's default decoder "systemd" claims every program name containing "systemd", so journald's lines use it instead of an own decoder.
JOURNALD_DECODER = "systemd"
SAMPLE_PROGRAMS = (*OWN_TAGS, JOURNALD_PROGRAM)
# Exception: OpenSSH 9.8+ logs sessions and failed logins as sshd-session; the listener still logs as sshd.
SYSTEM_TAGS = ("sshd", "sshd-session", "sudo")
CONTAINER_COMM = "dockerd"
RESERVED_TAGS = (*OWN_TAGS, JOURNALD_PROGRAM, *SYSTEM_TAGS, CONTAINER_COMM)
PROVIDER_ENTITY = "wazuh"
MANAGER_ROLE = "web-app-wazuh"
SAMPLES_FILE = "samples.yml"
AGENT_ID = "001"
AGENT_TIME_RECONNECT = 60


def decoder_name(entity: str) -> str:
    """Return the base parent decoder name of an app tag.

    Args:
        entity: the role's entity name, which is its journald tag.
    """
    return f"infinito-{entity}"


def docker_rule_ids(rule_block: int) -> dict[str, int]:
    """Return the central Docker attribution rule IDs of an app block.

    Args:
        rule_block: the app's ``services.wazuh.rule_block``.

    Returns:
        ``{oom, healthcheck, swarm, compose}`` rule IDs at the top of the block.
    """
    return {kind: rule_block + offset for kind, offset in DOCKER_RULE_OFFSETS.items()}


def load_samples(path: Path) -> list[dict[str, Any]]:
    """Return a role's samples with ``log`` normalised to a list of lines.

    Args:
        path: the role's ``files/wazuh/samples.yml``; absent means no samples.

    Returns:
        ``[{lines, rule, level}]`` in file order, plus ``program`` where the
        sample names one (only the Wazuh role's own-tag samples do).
    """
    samples = load_yaml_any(str(path), default_if_missing=[]) or []
    return [
        {
            "lines": [sample["log"]] if isinstance(sample["log"], str) else list(sample["log"]),
            "rule": sample["rule"],
            "level": sample["level"],
            **({"program": sample["program"]} if "program" in sample else {}),
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
            elif rule_id >= start + APP_RULE_LIMIT:
                errors.append(
                    f"{role}: rule id {rule_id} is reserved; {start + APP_RULE_LIMIT}-{block[-1]} "
                    "hold the central Docker attribution rules"
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
    role: str,
    wazuh_dir: Path,
    allowed: range,
    correlation: dict[int, bool],
    programs: tuple[str, ...] = (),
) -> list[str]:
    path = wazuh_dir / SAMPLES_FILE
    samples = load_yaml_any(str(path), default_if_missing=[]) or []
    if not isinstance(samples, list):
        return [f"{path}: must be a list of {{log, rule, level}}"]
    errors: list[str] = []
    covered: set[int] = set()
    keys = {"log", "rule", "level"}
    for index, sample in enumerate(samples):
        where = f"{role}: sample {index + 1}"
        if not isinstance(sample, dict) or not (
            set(sample) == keys or (programs and set(sample) == keys | {"program"})
        ):
            errors.append(
                f"{where}: needs exactly the keys log, rule, level"
                + (", and optionally program" if programs else "")
            )
            continue
        if "program" in sample and sample["program"] not in programs:
            errors.append(f"{where}: program must be one of {', '.join(programs)}")
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


def _opted_in(application: dict[str, Any]) -> bool:
    services = application.get("services") or {}
    wazuh = services.get("wazuh") if isinstance(services, dict) else None
    return isinstance(wazuh, dict) and "enabled" in wazuh


def tag_errors(applications: dict[str, Any], roles_dir: Path) -> list[str]:
    """Check that every opted-in role's journald tag is usable and its own.

    Args:
        applications: role id to merged application defaults.
        roles_dir: the directory holding every role, opted in or not.

    Returns:
        One message per opted-in role whose entity name, which is both its
        journald tag and its compose project, is empty, is one of the
        ``RESERVED_TAGS``, contains the name Wazuh's default ``systemd``
        decoder claims, or is also the entity of another role.
    """
    owners: dict[str, list[str]] = {}
    for path in sorted(roles_dir.iterdir()):
        if path.is_dir():
            owners.setdefault(get_entity_name(path.name), []).append(path.name)
    errors: list[str] = []
    for role in sorted(applications):
        entity = get_entity_name(role)
        if entity == PROVIDER_ENTITY or not _opted_in(applications[role]):
            continue
        if not entity:
            errors.append(f"{role}: an opted-in role needs a non-empty entity name for its Wazuh tag")
            continue
        if entity in RESERVED_TAGS:
            errors.append(f"{role}: Wazuh tag '{entity}' is reserved for the agent or the ruleset")
        elif JOURNALD_DECODER in entity:
            errors.append(
                f"{role}: Wazuh tag '{entity}' contains '{JOURNALD_DECODER}', which Wazuh's default decoder claims"
            )
        others = [other for other in owners.get(entity, []) if other != role]
        if others:
            errors.append(
                f"{role}: Wazuh tag '{entity}' is also the entity of {', '.join(others)}; "
                "their logs and Docker events would mix"
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
                _sample_errors(
                    role, wazuh_dir, range(BASE_RULE_MIN, BASE_RULE_MAX + 1), {}, SAMPLE_PROGRAMS
                )
            )
            continue
        services = applications[role].get("services") or {}
        wazuh = services.get("wazuh") if isinstance(services, dict) else None
        opted_in = _opted_in(applications[role])
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
            _sample_errors(role, wazuh_dir, range(start, start + APP_RULE_LIMIT), correlation)
        )
    blocks.sort()
    errors.extend(
        f"{role} and {next_role}: rule blocks {start} and {next_start} overlap"
        for (start, role), (next_start, next_role) in zip(blocks, blocks[1:])
        if next_start < start + RULE_BLOCK_SIZE
    )
    return errors
