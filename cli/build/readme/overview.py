"""Generate the invokable-role overview table in the repository README.

Usage:
  python -m cli.build.readme.overview [--check] [--readme PATH] [--roles-dir DIR]

The table lives in its own ``## Roles Overview 🧩`` section directly above
``## Get Started 🚀`` in the root README.md and is fully regenerated on every
run; every other section stays untouched. Rows are the invokable roles,
sorted ascending by the Entity column.

Rows are the invokable roles, sorted ascending by name.

Columns:
  Name             Role README H1 title, linked to the role directory.
  Lifecycle        Role lifecycle stage (alpha/beta/rc/stable/...).
  Homepage         ``homepage`` from meta/info.yml, empty when absent.
  Video            ``video`` from meta/info.yml as an emoji link, empty when absent.
  Description      ``galaxy_info.description`` from meta/main.yml.
  Integrated with  README titles of the role's direct service integrations
                   (complexity graph, level 1), linked to the roles.
  Install          Emoji link to the role README's Quick Setup section.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from cli.meta.roles.applications.complexity.model import compute_complexity_rows
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_README,
)
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

SECTION_HEADING = "## Roles Overview 🧩"
ANCHOR_HEADING = "## Get Started 🚀"
COLUMNS = (
    "Name",
    "Lifecycle",
    "Homepage",
    "Video",
    "Description",
    "Integrated with",
    "Install",
)
_VIDEO_EMOJI = "🎬"
_INSTALL_EMOJI = "🛠️"


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


def _homepage(roles_dir: Path, role: str) -> str:
    url = _info_url(roles_dir, role, "homepage")
    if not url:
        return ""
    label = urlparse(url).netloc.removeprefix("www.") or url
    return f"[{label}]({url})"


def _video(roles_dir: Path, role: str) -> str:
    url = _info_url(roles_dir, role, "video")
    return f"[{_VIDEO_EMOJI}]({url})" if url else ""


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
                _homepage(roles_dir, role),
                _video(roles_dir, role),
                _cell(_description(roles_dir, role)),
                ", ".join(f"[{title}](roles/{dep}/)" for title, dep in integrated),
                f"[{_INSTALL_EMOJI}](roles/{role}/{ROLE_FILE_README}#quick-setup)",
            )
        )

    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def replace_section(readme_text: str, table: str) -> str:
    section = f"{SECTION_HEADING}\n\n{table}\n\n"
    lines = readme_text.splitlines(keepends=True)

    if any(line.rstrip("\n") == SECTION_HEADING for line in lines):
        out: list[str] = []
        in_section = False
        for line in lines:
            stripped = line.rstrip("\n")
            if stripped == SECTION_HEADING:
                in_section = True
                out.append(section)
                continue
            if in_section and stripped.startswith("## "):
                in_section = False
            if not in_section:
                out.append(line)
        return "".join(out)

    out = []
    inserted = False
    for line in lines:
        if not inserted and line.rstrip("\n") == ANCHOR_HEADING:
            out.append(section)
            inserted = True
        out.append(line)
    if not inserted:
        raise ValueError(f"anchor heading {ANCHOR_HEADING!r} not found in README")
    return "".join(out)


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
