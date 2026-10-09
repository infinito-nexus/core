from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README

_README_TITLE = re.compile(r"^#\s+(.*)$")


def _readme_title(readme, fallback):
    if not readme.exists():
        return fallback
    try:
        lines = readme.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Error reading {readme}: {exc}")
        return fallback
    return next(
        (
            match.group(1).strip()
            for line in lines
            if (match := _README_TITLE.match(line))
        ),
        fallback,
    )


def collect_roles_by_tag(roles_dir):
    """Group every role below ``roles_dir`` by its galaxy tags.

    Args:
        roles_dir: directory holding one sub-directory per role.

    Returns:
        ``{tag: [role, ...]}`` where each role is a dict with ``name``,
        ``title``, ``description``, ``link`` and ``tags``. A role without
        tags lands under ``uncategorized``.
    """
    categories = {}
    for role_path in Path(roles_dir).iterdir():
        if not role_path.is_dir() or role_path.name.startswith("."):
            continue
        meta_path = role_path / ROLE_FILE_META_MAIN
        if not meta_path.exists():
            print(f"{ROLE_FILE_META_MAIN} not found for role {role_path}")
            continue
        try:
            data = load_yaml(str(meta_path))
        except (OSError, TypeError, yaml.YAMLError) as exc:
            print(f"Error reading YAML file {meta_path}: {exc}")
            continue

        galaxy_info = data.get("galaxy_info", {})
        tags = galaxy_info.get("galaxy_tags", []) or ["uncategorized"]
        entry = {
            "name": role_path.name,
            "title": _readme_title(role_path / ROLE_FILE_README, role_path.name),
            "description": galaxy_info.get("description", ""),
            "link": f"roles/{role_path.name}/{ROLE_FILE_README}",
            "tags": tags,
        }
        for tag in tags:
            categories.setdefault(tag, []).append(entry)
    return categories


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write the roles overview the roles-overview directive renders."
    )
    parser.add_argument("--roles-dir", required=True, help="Directory of the roles.")
    parser.add_argument("--output-file", required=True, help="JSON file to write.")
    args = parser.parse_args(argv)

    output = Path(args.output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(collect_roles_by_tag(args.roles_dir), indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
