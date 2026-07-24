"""Generate the invokable-role overview table in the repository README.

Usage:
  python -m cli.build.readme.overview [--check] [--readme PATH] [--roles-dir DIR]

The table lives in its own ``## Roles Overview 🧩`` section directly above
``## Use it online 🚀`` in the root README.md and is fully regenerated on every
run; every other section stays untouched. Rows are the invokable roles,
sorted ascending by the Entity column.

Rows are the invokable roles inside the tested lifecycle envelope, sorted
ascending by name.

Columns:
  Name             Role README H1 title, linked to the role directory.
  Status           Role lifecycle stage.
  Description      ``galaxy_info.description`` from meta/main.yml.
  More             Emoji links: 🌐 homepage, 🎬 video (both from
                   meta/info.yml, omitted when absent) and 🛠️ the role
                   README's Quick Setup section.
  Integrated with  README titles of the role's direct service integrations
                   (complexity graph, level 1), linked to the roles.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from cli.meta.roles.applications.complexity.model import compute_complexity_rows
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.lifecycle import tested_lifecycles
from utils.roles.mapping import (
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_README,
)
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

SECTION_HEADING = "## Roles Overview 🧩"
ANCHOR_HEADING = "## Use it online 🚀"
COLUMNS = (
    "Name",
    "Status",
    "Description",
    "More",
    "Integrated with",
)
_HOME_EMOJI = "🌐"
_VIDEO_EMOJI = "🎬"
_INSTALL_EMOJI = "🛠️"
_TESTED_ENVELOPE = tested_lifecycles()
_INTRO = (
    "Every invokable role in the tested lifecycle envelope, with its upstream "
    "homepage, an introduction video, the roles it integrates with, and a "
    "one-command local install."
)


def _cell(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def _load_dict(path: Path) -> dict:
    data = load_yaml_any(str(path), default_if_missing={}) or {}
    return data if isinstance(data, dict) else {}


def _role_title(roles_dir: Path, role: str) -> str:
    readme = roles_dir / role / ROLE_FILE_README
    if readme.is_file():
        for line in read_text(str(readme)).splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    entity = get_entity_name(role) or role
    return entity.replace("-", " ").title()


def _more(roles_dir: Path, role: str) -> str:
    """Emoji links: homepage, video, and the local-install anchor."""
    links = []
    homepage = _info_url(roles_dir, role, "homepage")
    if homepage:
        links.append(f"[{_HOME_EMOJI}]({homepage})")
    video = _info_url(roles_dir, role, "video")
    if video:
        links.append(f"[{_VIDEO_EMOJI}]({video})")
    links.append(f"[{_INSTALL_EMOJI}](roles/{role}/{ROLE_FILE_README}#quick-setup)")
    return " ".join(links)


def _info_url(roles_dir: Path, role: str, key: str) -> str:
    url = _load_dict(roles_dir / role / ROLE_FILE_META_INFO).get(key)
    return url.strip() if isinstance(url, str) else ""


def _description(roles_dir: Path, role: str) -> str:
    galaxy = _load_dict(roles_dir / role / ROLE_FILE_META_MAIN).get("galaxy_info")
    description = galaxy.get("description") if isinstance(galaxy, dict) else None
    return description if isinstance(description, str) else ""


def build_table(roles_dir: Path) -> str:
    invokable_paths = _get_invokable_paths()
    roles = sorted(
        p.name
        for p in roles_dir.iterdir()
        if p.is_dir() and _is_role_invokable(p.name, invokable_paths)
    )
    complexity = {row.name: row for row in compute_complexity_rows(roles_dir)}
    roles = [
        role
        for role in roles
        if getattr(complexity.get(role), "lifecycle", "") in _TESTED_ENVELOPE
    ]
    titles = {role: _cell(_role_title(roles_dir, role)) for role in roles}

    rows = []
    for role in sorted(roles, key=lambda r: titles[r].casefold()):
        integrated = sorted(
            {
                (titles.get(dep) or _cell(_role_title(roles_dir, dep)), dep)
                for dep in getattr(complexity.get(role), "services_direct", [])
                if dep != role
            },
            key=lambda pair: pair[0].casefold(),
        )
        rows.append(
            (
                f"[{titles[role]}](roles/{role}/)",
                _cell(getattr(complexity.get(role), "lifecycle", "")),
                _cell(_description(roles_dir, role)),
                _more(roles_dir, role),
                ", ".join(f"[{title}](roles/{dep}/)" for title, dep in integrated),
            )
        )

    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def replace_section(readme_text: str, table: str) -> str:
    section = f"{SECTION_HEADING}\n\n{_INTRO}\n\n{table}\n\n"
    lines = readme_text.splitlines(keepends=True)

    kept: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.rstrip("\n")
        if stripped == SECTION_HEADING:
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## "):
                in_section = False
            else:
                continue
        kept.append(line)

    anchor = next(
        (i for i, line in enumerate(kept) if line.rstrip("\n") == ANCHOR_HEADING),
        None,
    )
    if anchor is None:
        raise ValueError(f"anchor heading {ANCHOR_HEADING!r} not found in README")
    insert_at = next(
        (
            i
            for i in range(anchor + 1, len(kept))
            if kept[i].rstrip("\n").startswith("## ")
        ),
        len(kept),
    )
    kept.insert(insert_at, section)
    return "".join(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the invokable-role overview table in the root README."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the README would change.",
    )
    parser.add_argument("--readme", default=str(PROJECT_ROOT / "README.md"))
    parser.add_argument("--roles-dir", default=str(PROJECT_ROOT / "roles"))
    args = parser.parse_args(argv)

    readme_path = Path(args.readme)
    roles_dir = Path(args.roles_dir)
    if not roles_dir.is_dir():
        parser.error(f"Roles directory not found: {roles_dir}")

    original = read_text(str(readme_path))
    updated = replace_section(original, build_table(roles_dir))

    if updated == original:
        print(f"{readme_path.name}: overview up to date")
        return 0
    if args.check:
        print(f"{readme_path.name}: overview outdated, run make readme-index")
        return 1
    readme_path.write_text(updated, encoding="utf-8")
    print(f"{readme_path.name}: overview updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
