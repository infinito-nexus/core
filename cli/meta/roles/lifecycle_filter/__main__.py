from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional, Set, Tuple

from utils.roles.meta_lookup import get_role_lifecycle


def _repo_root() -> Path:
    """
    Determine repository root by locating the 'cli/' directory.
    This makes the tool independent from the current working directory.
    """
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "cli").is_dir():
            return parent
    raise RuntimeError("Failed to locate repository root (missing 'cli/' directory).")


def _iter_role_dirs(roles_dir: Path) -> Iterable[Tuple[str, Path]]:
    """Yield ``(role_name, role_dir)`` for every directory under ``roles_dir``."""
    if not roles_dir.exists() or not roles_dir.is_dir():
        return

    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        yield role_dir.name, role_dir


def filter_roles(
    roles_dir: Path,
    mode: str,
    statuses: Set[str],
    selection: Optional[Set[str]] = None,
    include_missing_lifecycle_on_blacklist: bool = True,
) -> list[str]:
    matched: list[str] = []

    for role_name, role_dir in _iter_role_dirs(roles_dir):
        if selection is not None and role_name not in selection:
            continue

        try:
            lifecycle_value = get_role_lifecycle(role_dir, role_name=role_name)
        except Exception:
            # Best-effort: never fail discovery on a single broken role.
            lifecycle_value = None
        lifecycle = (lifecycle_value or "").strip().lower()

        if mode == "whitelist":
            if lifecycle in statuses:
                matched.append(role_name)
        else:  # blacklist
            if lifecycle == "":
                if include_missing_lifecycle_on_blacklist:
                    matched.append(role_name)
                continue

            if lifecycle not in statuses:
                matched.append(role_name)

    return sorted(matched)


def build_parser() -> argparse.ArgumentParser:
    default_roles_dir = _repo_root() / "roles"

    p = argparse.ArgumentParser(
        prog="infinito meta roles lifecycle_filter",
        description="Print role names (space-separated) filtered by galaxy_info.lifecycle "
        "in roles/*/meta/main.yml.\n\n"
        "Examples:\n"
        "  infinito meta roles lifecycle_filter whitelist stable rc\n"
        "  infinito meta roles lifecycle_filter blacklist deprecated eol\n"
        "  infinito meta roles lifecycle_filter whitelist stable "
        "--selection web-app-matomo docker-keycloak\n",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    p.add_argument(
        "mode",
        choices=["whitelist", "blacklist"],
        help="Filtering mode.",
    )
    p.add_argument(
        "statuses",
        nargs="+",
        help="Lifecycle statuses (space-separated), e.g. stable beta rc deprecated eol",
    )
    p.add_argument(
        "--roles-dir",
        type=Path,
        default=default_roles_dir,
        help=f"Roles directory to scan (default: {default_roles_dir})",
    )
    p.add_argument(
        "--selection",
        nargs="+",
        help="Optional whitelist of role names. "
        "Only roles contained in this list are returned if filters match.",
    )
    p.add_argument(
        "--exclude-missing",
        action="store_true",
        help="In blacklist mode: exclude roles with missing lifecycle instead of including them.",
    )

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    roles_dir: Path = args.roles_dir
    statuses = {s.strip().lower() for s in args.statuses if s.strip()}
    selection = (
        {s.strip() for s in args.selection if s.strip()} if args.selection else None
    )

    if not roles_dir.is_dir():
        print(f"Error: roles directory not found: {roles_dir}", file=sys.stderr)
        return 1

    try:
        role_names = filter_roles(
            roles_dir=roles_dir,
            mode=args.mode,
            statuses=statuses,
            selection=selection,
            include_missing_lifecycle_on_blacklist=not args.exclude_missing,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Output: role names separated by whitespaces
    sys.stdout.write(" ".join(role_names) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
