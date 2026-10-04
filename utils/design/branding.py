"""Logo and title resolution for the corporate design."""

from __future__ import annotations

import re
from pathlib import Path

from utils.cache.files import read_text

DESIGN_ROLE = "web-svc-design"
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def is_disabled(value: object) -> bool:
    """Tell whether a logo or title value switches the replacement off.

    Args:
        value: Raw configuration value.

    Returns:
        ``True`` for ``false`` and ``0`` in any YAML or templated spelling.
    """
    return str(value).strip().lower() in {"false", "0", "no"}


def role_title(roles_dir: Path, application_id: str) -> str:
    """Return the first H1 of the role README.

    Args:
        roles_dir: Directory holding the roles.
        application_id: Role name.

    Returns:
        The H1 text.

    Raises:
        ValueError: When the README has no H1.
    """
    readme = roles_dir / application_id / "README.md"
    match = _H1_RE.search(read_text(str(readme)))
    if not match:
        raise ValueError(f"{readme} has no H1 to derive the design title from")
    return match.group(1)


def _slots(raw: dict) -> dict[str, dict]:
    slots = {}
    for name, spec in raw.items():
        width, height = int(spec["width"]), int(spec["height"])
        if width <= 0 or height <= 0:
            raise ValueError(f"design slot {name!r} needs a positive width and height")
        slots[name] = {
            "width": width,
            "height": height,
            "text_only": bool(spec.get("text_only", False)),
        }
    return slots


def resolve_branding(
    applications: dict, application_id: str, project_root: Path
) -> dict[str, object]:
    """Resolve logo, title and slots for one role.

    A key set in the role's own ``services.design`` entry wins over the
    ``web-svc-design`` value; ``false``/``0`` disables the replacement for
    that scope, and a ``true`` title resolves to the role README H1.

    Args:
        applications: Merged applications mapping.
        application_id: Role to resolve.
        project_root: Repository root; relative logo paths resolve against it.

    Returns:
        ``{"logo": <absolute path> | False, "title": <str> | False,
        "name": <README H1>, "label": <title, else name>,
        "slots": {name: {"width", "height", "text_only"}}}``. ``label`` serves
        installers that require a site name even when the title replacement
        is disabled.

    Raises:
        ValueError: When the logo file is missing, a slot is malformed or the
            fallback title cannot be derived.
    """
    global_cfg = applications[DESIGN_ROLE]["services"]["design"]
    role_cfg = applications[application_id]["services"].get("design") or {}

    def pick(key: str) -> object:
        return role_cfg[key] if key in role_cfg else global_cfg[key]

    logo = pick("logo")
    if is_disabled(logo):
        logo = False
    else:
        path = Path(str(logo))
        path = path if path.is_absolute() else project_root / path
        if not path.is_file():
            raise ValueError(f"design logo for {application_id!r} not found: {path}")
        logo = str(path)

    name = role_title(project_root / "roles", application_id)
    title = pick("title")
    if str(title).strip().lower() == "true":
        title = name
    elif is_disabled(title):
        title = False
    else:
        title = str(title)

    return {
        "logo": logo,
        "title": title,
        "name": name,
        "label": title or name,
        "slots": _slots({**global_cfg["slots"], **(role_cfg.get("slots") or {})}),
    }
