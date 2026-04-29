# utils/invokable.py
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Set

from utils.cache.yaml import load_yaml_any


@dataclass(frozen=True)
class DeploymentTypeRule:
    name: str
    include_re: re.Pattern[str]
    exclude_re: re.Pattern[str] | None


DEFAULT_RULES: tuple[DeploymentTypeRule, ...] = (
    DeploymentTypeRule(
        name="server",
        include_re=re.compile(r"^(web-app-|web-svc-)"),
        exclude_re=re.compile(r"^(web-app-oauth2-proxy)$"),
    ),
    DeploymentTypeRule(
        name="workstation",
        include_re=re.compile(r"^(desk-|util-desk-)"),
        exclude_re=None,
    ),
    # "universal": everything invokable that is not matched by server/workstation rules
    DeploymentTypeRule(
        name="universal",
        include_re=re.compile(r".*"),
        exclude_re=None,
    ),
)


def _repo_root() -> Path:
    # utils/invokable.py -> utils -> repo root
    return Path(__file__).resolve().parents[1]


def _roles_dir() -> Path:
    return _repo_root() / "roles"


def _categories_file() -> Path:
    return _roles_dir() / "categories.yml"


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = load_yaml_any(str(path), default_if_missing={})
    return data if isinstance(data, dict) else {}


def _role_lifecycle(role_dir: Path) -> str:
    # Per req-010 `lifecycle` lives on the role's primary entity at
    # `meta/services.yml.<primary_entity>.lifecycle`. Delegate to the
    # canonical helper and treat any failure as "no lifecycle" so role
    # discovery is never broken by a single malformed meta file.
    from utils.roles.meta_lookup import get_role_lifecycle

    try:
        value = get_role_lifecycle(role_dir, role_name=role_dir.name)
    except Exception:
        return ""
    return value or ""


def _get_invokable_paths() -> list[str]:
    from plugins.filter.invokable_paths import get_invokable_paths  # type: ignore

    paths = get_invokable_paths(str(_categories_file()))
    if not paths:
        raise RuntimeError("No invokable paths found in categories.yml")
    return [str(p) for p in paths]


def _is_role_invokable(role_name: str, invokable_paths: Iterable[str]) -> bool:
    # Matches your existing logic:
    # role == p or role.startswith(p + "-")
    for p in invokable_paths:
        if role_name == p or role_name.startswith(p + "-"):
            return True
    return False


def _role_to_app_id(role_dir: Path) -> str:
    vars_file = role_dir / "vars" / "main.yml"
    if not vars_file.is_file():
        return role_dir.name

    try:
        data = _read_yaml(vars_file)
        app_id = data.get("application_id")
        return str(app_id) if app_id else role_dir.name
    except Exception:
        return role_dir.name


def list_invokable_app_ids() -> list[str]:
    roles_dir = _roles_dir()
    invokable_paths = _get_invokable_paths()
    if not invokable_paths or not roles_dir.is_dir():
        return []

    result: list[str] = []
    for role_dir in sorted(
        [p for p in roles_dir.iterdir() if p.is_dir()], key=lambda p: p.name
    ):
        if _is_role_invokable(role_dir.name, invokable_paths):
            result.append(_role_to_app_id(role_dir))

    return sorted(set(result))


def _rule_matches_role_name(rule: DeploymentTypeRule, role_name: str) -> bool:
    if not rule.include_re.search(role_name):
        return False
    if rule.exclude_re and rule.exclude_re.search(role_name):
        return False
    return True


def list_invokables_by_type(
    *,
    rules: Iterable[DeploymentTypeRule] = DEFAULT_RULES,
    lifecycles: Set[str] | None = None,
) -> dict[str, list[str]]:
    """
    Returns:
      {
        "server": [...],
        "workstation": [...],
        "universal": [...],
      }

    "universal" = invokable roles that are NOT matched by any other non-universal rule.

    If lifecycles is provided, only roles whose galaxy_info.lifecycle is in the set
    are included. Missing lifecycle is treated as "not matching".
    """
    roles_dir = _roles_dir()
    invokable_paths = _get_invokable_paths()
    if not invokable_paths or not roles_dir.is_dir():
        return {r.name: [] for r in rules}

    # Gather invokable role dirs first (+ optional lifecycle gating)
    invokable_role_dirs: list[Path] = []
    for role_dir in sorted(
        [p for p in roles_dir.iterdir() if p.is_dir()], key=lambda p: p.name
    ):
        if not _is_role_invokable(role_dir.name, invokable_paths):
            continue

        if lifecycles is not None:
            lc = _role_lifecycle(role_dir)
            if not lc or lc not in lifecycles:
                continue

        invokable_role_dirs.append(role_dir)

    # Identify non-universal rules for subtraction logic
    rules_list = list(rules)
    non_universal = [r for r in rules_list if r.name != "universal"]

    by_type: dict[str, list[str]] = {r.name: [] for r in rules_list}

    # First pass: server/workstation buckets
    claimed_role_names: set[str] = set()
    for role_dir in invokable_role_dirs:
        for r in non_universal:
            if _rule_matches_role_name(r, role_dir.name):
                by_type[r.name].append(_role_to_app_id(role_dir))
                claimed_role_names.add(role_dir.name)
                break

    # Second pass: universal = remaining invokables
    if "universal" in by_type:
        for role_dir in invokable_role_dirs:
            if role_dir.name not in claimed_role_names:
                by_type["universal"].append(_role_to_app_id(role_dir))

    # Normalize sort + unique
    for k, v in by_type.items():
        by_type[k] = sorted(set(v))

    return by_type


def types_from_group_names(
    group_names: Iterable[str],
    *,
    rules: Iterable[DeploymentTypeRule] = DEFAULT_RULES,
) -> list[str]:
    """
    SPOT:
      - invokable is defined by categories.yml via _get_invokable_paths()/_is_role_invokable()
      - server/workstation/universal classification is defined by DEFAULT_RULES

    Semantics:
      universal = invokable AND NOT matched by any non-universal rule.
    """
    names = [str(g).strip() for g in (group_names or []) if str(g).strip()]
    if not names:
        return []

    invokable_paths = _get_invokable_paths()
    invokable_names = [g for g in names if _is_role_invokable(g, invokable_paths)]
    if not invokable_names:
        return []

    rules_list = list(rules)
    non_universal = [r for r in rules_list if r.name != "universal"]

    matched: set[str] = set()
    claimed: set[str] = set()

    # server/workstation via rules
    for g in invokable_names:
        for r in non_universal:
            if _rule_matches_role_name(r, g):
                matched.add(r.name)
                claimed.add(g)
                break

    # universal = invokable leftovers (not claimed by server/workstation)
    if any(g not in claimed for g in invokable_names):
        matched.add("universal")

    return sorted(matched)
