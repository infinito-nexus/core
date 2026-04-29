from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from utils.cache.yaml import load_yaml_any


def _find_project_root(start: Path) -> Optional[Path]:
    """
    Walk upwards from `start` until we find a repository root marker.
    We treat `roles/categories.yml` as the canonical marker for this project.
    """
    start = start.resolve()
    candidates = [start, *start.parents]
    for p in candidates:
        if (p / "roles" / "categories.yml").is_file():
            return p
    return None


def _default_roles_file() -> str:
    """
    Determine the default roles/categories.yml path robustly.
    Priority:
      1) current working directory (common for CLI usage)
      2) location of this file (common for ansible execution from repo)
    """
    root = _find_project_root(Path.cwd())
    if root is None:
        root = _find_project_root(Path(__file__).resolve().parent)
    if root is None:
        # Keep the error explicit and helpful
        raise FileNotFoundError(
            "Could not locate project root containing roles/categories.yml. "
            "Run from the repo root or pass roles_file explicitly."
        )
    return str(root / "roles" / "categories.yml")


def get_invokable_paths(
    roles_file: Optional[str] = None, suffix: Optional[str] = None
) -> List[str]:
    """
    Load nested roles YAML and return dash-joined paths where 'invokable' is True.
    Appends suffix if provided.
    """
    if not roles_file:
        roles_file = _default_roles_file()

    try:
        data = load_yaml_any(roles_file, default_if_missing={}) or {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Roles file not found: {roles_file}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML {roles_file}: {e}")

    if not isinstance(data, dict):
        raise ValueError("YAML root is not a dictionary")

    roles = data
    if "roles" in roles and isinstance(roles["roles"], dict) and len(roles) == 1:
        roles = roles["roles"]

    def _recurse(
        subroles: Dict[str, dict], parent: Optional[List[str]] = None
    ) -> List[str]:
        parent = parent or []
        found: List[str] = []
        METADATA = {"title", "description", "icon", "invokable"}

        for key, cfg in subroles.items():
            path = parent + [key]
            if cfg.get("invokable", False):
                p = "-".join(path)
                if suffix:
                    p += suffix
                found.append(p)

            children = {
                ck: cv
                for ck, cv in cfg.items()
                if ck not in METADATA and isinstance(cv, dict)
            }
            if children:
                found.extend(_recurse(children, path))
        return found

    return _recurse(roles)


def get_non_invokable_paths(
    roles_file: Optional[str] = None, suffix: Optional[str] = None
) -> List[str]:
    """
    Load nested roles YAML and return dash-joined paths where 'invokable' is False or missing.
    Appends suffix if provided.
    """
    if not roles_file:
        roles_file = _default_roles_file()

    try:
        data = load_yaml_any(roles_file, default_if_missing={}) or {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Roles file not found: {roles_file}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML {roles_file}: {e}")

    if not isinstance(data, dict):
        raise ValueError("YAML root is not a dictionary")

    roles = data
    if "roles" in roles and isinstance(roles["roles"], dict) and len(roles) == 1:
        roles = roles["roles"]

    def _recurse_non(
        subroles: Dict[str, dict], parent: Optional[List[str]] = None
    ) -> List[str]:
        parent = parent or []
        found: List[str] = []
        METADATA = {"title", "description", "icon", "invokable"}

        for key, cfg in subroles.items():
            path = parent + [key]
            p = "-".join(path)
            inv = cfg.get("invokable", False)
            if not inv:
                found.append(p + (suffix or ""))

            children = {
                ck: cv
                for ck, cv in cfg.items()
                if ck not in METADATA and isinstance(cv, dict)
            }
            if children:
                found.extend(_recurse_non(children, path))
        return found

    return _recurse_non(roles)


class FilterModule:
    def filters(self):
        return {
            "invokable_paths": get_invokable_paths,
            "non_invokable_paths": get_non_invokable_paths,
        }
