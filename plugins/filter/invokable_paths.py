from __future__ import annotations

import yaml

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any

_METADATA_KEYS = frozenset({"title", "description", "icon", "invokable", "modes"})


def _default_roles_file() -> str:
    categories = ROLES_DIR / "categories.yml"
    if not categories.is_file():
        raise FileNotFoundError(
            f"Could not locate {categories}. Pass roles_file explicitly."
        )
    return str(categories)


def get_invokable_paths(
    roles_file: str | None = None, suffix: str | None = None
) -> list[str]:
    """
    Load nested roles YAML and return dash-joined paths where 'invokable' is True.
    Appends suffix if provided.
    """
    if not roles_file:
        roles_file = _default_roles_file()

    try:
        data = load_yaml_any(roles_file, default_if_missing={}) or {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Roles file not found: {roles_file}") from None
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML {roles_file}: {e}") from e

    if not isinstance(data, dict):
        raise TypeError("YAML root is not a dictionary")

    roles = data
    if "roles" in roles and isinstance(roles["roles"], dict):
        roles = roles["roles"]

    def _recurse(
        subroles: dict[str, dict], parent: list[str] | None = None
    ) -> list[str]:
        parent = parent or []
        found: list[str] = []

        for key, cfg in subroles.items():
            path = [*parent, key]
            if cfg.get("invokable", False):
                p = "-".join(path)
                if suffix:
                    p += suffix
                found.append(p)

            children = {
                ck: cv
                for ck, cv in cfg.items()
                if ck not in _METADATA_KEYS and isinstance(cv, dict)
            }
            if children:
                found.extend(_recurse(children, path))
        return found

    return _recurse(roles)


def get_non_invokable_paths(
    roles_file: str | None = None, suffix: str | None = None
) -> list[str]:
    """
    Load nested roles YAML and return dash-joined paths where 'invokable' is False or missing.
    Appends suffix if provided.
    """
    if not roles_file:
        roles_file = _default_roles_file()

    try:
        data = load_yaml_any(roles_file, default_if_missing={}) or {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Roles file not found: {roles_file}") from None
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML {roles_file}: {e}") from e

    if not isinstance(data, dict):
        raise TypeError("YAML root is not a dictionary")

    roles = data
    if "roles" in roles and isinstance(roles["roles"], dict):
        roles = roles["roles"]

    def _recurse_non(
        subroles: dict[str, dict], parent: list[str] | None = None
    ) -> list[str]:
        parent = parent or []
        found: list[str] = []

        for key, cfg in subroles.items():
            path = [*parent, key]
            p = "-".join(path)
            inv = cfg.get("invokable", False)
            if not inv:
                found.append(p + (suffix or ""))

            children = {
                ck: cv
                for ck, cv in cfg.items()
                if ck not in _METADATA_KEYS and isinstance(cv, dict)
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
