#!/usr/bin/env python3
"""
cli/meta/callorder/__main__.py

What it does:
- 📄 Prints the call order of roles per tasks/groups/*.yml
- 🎯 With --marker (and no --call): shows all groups/roles split into ✅ called (<= marker) vs ⏳ remaining (> marker)
- 🧩 With --call: filters to only groups that contain at least one of the selected roles and shows split vs marker (if given)
- 🧷 Lists groups "not effected by marker" (i.e., groups that do NOT contain the marker role)
- 🔎 --effected: when --marker or --call is set, show only groups that are effected (contain the marker role).
  If no --marker is set, --effected has no extra effect (because "effected by marker" is undefined).

Examples:
  # 1) Print call order per group file
  python -m cli.meta.callorder

  # 2) Marker-only view: show everything before/after marker
  python -m cli.meta.callorder --marker "web-app-nextcloud"

  # 3) Filter to selected roles and split relative to marker
  python -m cli.meta.callorder \
    --call "web-app-akaunting web-app-bigbluebutton web-app-bookwyrm web-app-chess web-app-discourse web-app-funkwhale web-app-matrix web-app-mediawiki web-app-nextcloud" \
    --marker "web-app-nextcloud"

  # 4) Only show effected groups (groups containing the marker role)
  python -m cli.meta.callorder --marker "web-app-nextcloud" --effected
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.cache.yaml import load_yaml_any as _load_yaml_cached


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def repo_root_from_this_script() -> Path:
    """
    Compute repo root *only* from this script's absolute location.

    Expected layout:
      <repo_root>/cli/meta/callorder/__main__.py

    Therefore:
      repo_root = Path(__file__).resolve().parents[3]
    """
    return Path(__file__).resolve().parents[3]


def list_group_files(groups_dir: Path) -> List[Path]:
    """
    Return group YAML files under tasks/groups (skip .gitignore and non-yml).
    Sort by filename for deterministic order.
    """
    out: List[Path] = []
    for p in groups_dir.iterdir():
        if not p.is_file():
            continue
        if p.name == ".gitignore":
            continue
        if p.suffix not in (".yml", ".yaml"):
            continue
        out.append(p)
    out.sort(key=lambda x: x.name)
    return out


def load_yaml(path: Path) -> Any:
    return _load_yaml_cached(str(path), default_if_missing=None)


def extract_roles_from_tasks(doc: Any) -> List[str]:
    """
    Extract include_role.name values from a task list.
    Ignores meta: flush_handlers (and everything else).
    """
    roles: List[str] = []
    if doc is None or not isinstance(doc, list):
        return roles

    for item in doc:
        if not isinstance(item, dict):
            continue

        inc = item.get("include_role")
        if isinstance(inc, dict):
            name = inc.get("name")
            if isinstance(name, str) and name.strip():
                roles.append(name.strip())

    return roles


def group_name_from_file(path: Path) -> str:
    """
    'web-app-roles.yml' -> 'web-app'
    'svc-db-roles.yml'  -> 'svc-db'
    If not matching '*-roles.yml', fall back to stem.
    """
    n = path.name
    if n.endswith("-roles.yml"):
        return n[: -len("-roles.yml")]
    if n.endswith("-roles.yaml"):
        return n[: -len("-roles.yaml")]
    return path.stem


@dataclass(frozen=True)
class Group:
    file: Path
    group_name: str
    roles: List[str]


def build_groups(repo_root: Path) -> List[Group]:
    groups_dir = repo_root / "tasks" / "groups"
    files = list_group_files(groups_dir)

    groups: List[Group] = []
    for f in files:
        doc = load_yaml(f)
        roles = extract_roles_from_tasks(doc)
        groups.append(Group(file=f, group_name=group_name_from_file(f), roles=roles))
    return groups


def flatten_callorder(groups: List[Group]) -> List[Tuple[str, str]]:
    """
    Global order across groups: (group_name, role) in file sort order.
    """
    out: List[Tuple[str, str]] = []
    for g in groups:
        for r in g.roles:
            out.append((g.group_name, r))
    return out


def normalize_call_list(s: str) -> List[str]:
    return [x.strip() for x in s.split() if x.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cli.meta.callorder",
        description="Print role call order per tasks/groups/*.yml and analyze relative to a marker role.",
    )
    ap.add_argument(
        "--call",
        help='Space-separated roles to analyze (filters groups), e.g. --call "web-app-a web-app-b".',
        default=None,
    )
    ap.add_argument(
        "--marker",
        help="Marker role name; splits roles into called vs remaining.",
        default=None,
    )
    ap.add_argument(
        "--effected",
        action="store_true",
        help="If --marker or --call is set: show only groups containing the marker role (effected groups).",
    )

    args = ap.parse_args(argv)

    repo_root = repo_root_from_this_script()
    groups = build_groups(repo_root)
    global_order = flatten_callorder(groups)

    # Build global index for marker comparisons.
    global_index: Dict[str, int] = {}
    for i, (_grp, role) in enumerate(global_order):
        global_index.setdefault(role, i)

    call_set: Optional[set[str]] = None
    if args.call:
        call_set = set(normalize_call_list(args.call))

    marker_role = (args.marker or "").strip() or None
    marker_pos: Optional[int] = None
    marker_group: Optional[str] = None
    if marker_role:
        if marker_role in global_index:
            marker_pos = global_index[marker_role]
            marker_group = global_order[marker_pos][0]
        else:
            eprint(f"⚠️  Marker role not found in any group file: {marker_role!r}")

    def role_is_called(role: str) -> bool:
        """
        Called means: appears at or before marker position.
        If marker is missing/not provided, treat as called for marker-less mode.
        """
        if marker_pos is None:
            return True
        idx = global_index.get(role)
        if idx is None:
            return False
        return idx <= marker_pos

    def role_marker_icon(role: str) -> str:
        return " 🎯" if marker_role and role == marker_role else ""

    # --- Mode 1: no --call and no --marker -> simple listing
    if call_set is None and marker_role is None:
        for g in groups:
            print(f"📂 {g.group_name}  ({g.file.relative_to(repo_root)})")
            if not g.roles:
                print("  · (no roles found)")
            else:
                for r in g.roles:
                    print(f"  - {r}")
            print()
        return 0

    # Decide group filtering:
    # - If --call: only groups that contain at least one selected role
    # - Else: all groups
    filtered_groups: List[Group] = []
    for g in groups:
        if call_set is not None:
            if any(r in call_set for r in g.roles):
                filtered_groups.append(g)
        else:
            filtered_groups.append(g)

    # Apply --effected: only groups that contain marker role (if marker exists)
    if args.effected and marker_role:
        filtered_groups = [g for g in filtered_groups if marker_role in g.roles]

    # Header
    print("🧾 === Callorder analysis ===")
    print(f"📍 Repo root: {repo_root}")
    if call_set is not None:
        print(f"🧩 Selected roles (--call): {len(call_set)}")
    else:
        print("🧩 Selected roles (--call): (none) — showing all groups")
    print(f"🎯 Marker (--marker): {marker_role or '(none)'}")
    if marker_role and marker_pos is not None:
        print(f"🧭 Marker location: group '{marker_group}' (global index {marker_pos})")
    print()

    # If marker exists, compute not-effected-by-marker groups (marker not present in group)
    if marker_role:
        not_effected = [g.group_name for g in groups if marker_role not in g.roles]
    else:
        not_effected = []

    # Helper for marker-only group positioning label
    def group_position_label(g: Group) -> str:
        if marker_pos is None:
            return ""
        indices = [global_index.get(r) for r in g.roles if r in global_index]
        if not indices:
            return "❔"
        if max(indices) <= marker_pos:
            return "⬅️  (before/equal marker)"
        if min(indices) > marker_pos:
            return "➡️  (after marker)"
        return "🎯 (spans marker)"

    # Print groups
    printed_any = False
    for g in filtered_groups:
        # Determine roles within scope
        if call_set is not None:
            scoped = [r for r in g.roles if r in call_set]
        else:
            scoped = list(g.roles)

        if not scoped:
            continue

        printed_any = True

        pos_label = group_position_label(g) if marker_role else ""
        print(f"📂 {g.group_name} {pos_label}  ({g.file.name})")

        if marker_role:
            called = [r for r in scoped if role_is_called(r)]
            remaining = [r for r in scoped if r not in called]

            if called:
                print("  ✅ called (<= marker):")
                for r in called:
                    print(f"    - {r}{role_marker_icon(r)}")
            if remaining:
                print("  ⏳ remaining (> marker or unknown):")
                for r in remaining:
                    print(f"    - {r}{role_marker_icon(r)}")
            if not called and not remaining:
                print("  · (no matching roles)")
        else:
            # --call without --marker: just list scoped roles
            for r in scoped:
                print(f"  - {r}")

        print()

    # Missing roles from --call not present in tasks/groups
    if call_set is not None:
        missing = sorted([r for r in call_set if r not in global_index])
        if missing:
            print("⚠️  === Roles not found in tasks/groups/*.yml ===")
            for r in missing:
                print(f"- {r}")
            print()

    # Not effected by marker list
    if marker_role:
        print(
            "🧷 === Not effected by marker (marker role not present in these groups) ==="
        )
        if not_effected:
            for gn in sorted(set(not_effected)):
                print(f"- {gn}")
        else:
            print("(none)")
        print()

    if not printed_any:
        if call_set is not None:
            print("ℹ️  No groups matched the provided --call roles.")
        else:
            print("ℹ️  Nothing to display (unexpected).")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
