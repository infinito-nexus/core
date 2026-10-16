#!/usr/bin/env python3
"""Generate or complete role README.md files from the schema template.

Usage:
  python -m cli.build.docs.readme [roles...] [--override] [--check] [--roles-dir DIR]

With no role names every role directory is processed. ``--override``
regenerates the managed sections (Architecture, Quick Setup, Credits) even
when they already exist; without it, only missing sections are added.
``--update-architecture`` regenerates only the Architecture section. Prose
sections are never rewritten. Every invokable role additionally gets an
``ARCHITECTURE.md`` sub-page. ``--check`` writes nothing and exits non-zero
when any file would change (for CI).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cli.build.docs.readme.generate import (
    MANAGED_SECTIONS,
    generate_architecture_page,
    generate_readme,
    role_dirs,
)
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_ARCHITECTURE, ROLE_FILE_README


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate role README.md files.")
    parser.add_argument("roles", nargs="*", help="Role names (default: all).")
    parser.add_argument(
        "--override",
        action="store_true",
        help="Regenerate managed sections even when present (default: only add missing).",
    )
    parser.add_argument(
        "--update-architecture",
        action="store_true",
        help="Regenerate only the Architecture section (implies override for it).",
    )
    parser.add_argument(
        "--update-quick-setup",
        action="store_true",
        help="Regenerate only the Quick Setup section (implies override for it).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if any README would change.",
    )
    parser.add_argument(
        "--roles-dir",
        default=str(PROJECT_ROOT / "roles"),
        help="Directory containing role subfolders.",
    )
    args = parser.parse_args()

    roles_root = Path(args.roles_dir)
    if not roles_root.is_dir():
        parser.error(f"Roles directory not found: {roles_root}")

    if args.roles:
        targets = [roles_root / name for name in args.roles]
        missing = [str(p) for p in targets if not p.is_dir()]
        if missing:
            parser.error("Unknown role(s): " + ", ".join(missing))
    else:
        targets = role_dirs(roles_root)

    if args.update_architecture:
        only, override = ("Architecture",), True
    elif args.update_quick_setup:
        only, override = ("Quick Setup",), True
    else:
        only, override = MANAGED_SECTIONS, args.override

    changed = 0
    for role_dir in targets:
        if (
            not (role_dir / ROLE_FILE_README).is_file()
            and not (role_dir / "meta").is_dir()
        ):
            continue
        new_text, actions = generate_readme(
            role_dir, role_dir.name, override=override, only=only
        )
        if new_text is None:
            continue
        changed += 1
        if args.check:
            print(f"would update roles/{role_dir.name}/README.md: {', '.join(actions)}")
            continue
        (role_dir / ROLE_FILE_README).write_text(new_text, encoding="utf-8")
        print(f"updated roles/{role_dir.name}/README.md: {', '.join(actions)}")

    for role_dir in targets:
        page = generate_architecture_page(role_dir, role_dir.name)
        if page is None:
            continue
        path = role_dir / ROLE_FILE_ARCHITECTURE
        if args.check:
            if not path.is_file() or read_text(str(path)) != page:
                print(f"would write roles/{role_dir.name}/{ROLE_FILE_ARCHITECTURE}")
                changed += 1
            continue
        path.write_text(page, encoding="utf-8")

    if args.check and changed:
        print(f"\n{changed} file(s) would change.")
        return 1
    if not args.check:
        print(f"\n{changed} file(s) written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
