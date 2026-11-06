"""HTML preview of every app's branding assets, rendered from one logo and base color."""

from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor
from html import escape
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.design.branding import DESIGN_ROLE, resolve_branding
from utils.design.logo import (
    LAYOUT_TITLE,
    choose_layout,
    is_monochrome,
    render_assets,
    render_png,
)
from utils.design.palette import build_palette
from utils.roles.mapping import ROLE_FILE_META_DOMAINS, ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_PAGE_CSS = """
body{margin:0;padding:16px;font-family:system-ui,sans-serif;background:#f4f4f2;color:#1b1b1b}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:24px 0 6px}p{margin:0 0 10px;color:#555;font-size:13px}
.slots{display:flex;flex-wrap:wrap;gap:12px}
.slot{border:1px solid #ccc;border-radius:8px;padding:8px;background:#fff;font-size:12px;max-width:100%}
.pair{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.tile{padding:10px;border-radius:6px;overflow:auto;max-width:100%}
.tile img{display:block;max-width:100%;height:auto}
"""


def design_roles(roles_dir: Path) -> list[str]:
    """List the roles that declare a ``design`` service entry.

    Args:
        roles_dir: Directory holding the roles.

    Returns:
        Sorted role names, without the design provider itself.
    """
    roles = []
    for services in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        role = services.parent.parent.name
        if role != DESIGN_ROLE and "design" in (load_yaml_any(str(services)) or {}):
            roles.append(role)
    return roles


def role_domain(roles_dir: Path, application_id: str, primary: str) -> str:
    """Render the first canonical domain of a role for a primary domain.

    Args:
        roles_dir: Directory holding the roles.
        application_id: Role name.
        primary: Value of ``DOMAIN_PRIMARY``.

    Returns:
        The canonical domain, or ``<application_id>.<primary>`` when the role
        declares none or its template needs more than ``DOMAIN_PRIMARY``.
    """
    path = roles_dir / application_id / ROLE_FILE_META_DOMAINS
    canonical = (
        (load_yaml_any(str(path)) or {}).get("canonical") if path.is_file() else None
    )
    while isinstance(canonical, (dict, list)) and canonical:
        canonical = (
            next(iter(canonical.values()))
            if isinstance(canonical, dict)
            else canonical[0]
        )
    rendered = (
        _substituted(str(canonical), {"DOMAIN_PRIMARY": primary}) if canonical else None
    )
    return rendered or f"{application_id}.{primary}"


def _substituted(text: str, context: dict) -> str | None:
    """Replace ``{{ NAME }}`` placeholders from a mapping.

    Args:
        text: Text carrying plain variable placeholders.
        context: Values by variable name.

    Returns:
        The text with every placeholder replaced, or ``None`` when a
        placeholder names a missing variable or the text holds other Jinja.
    """
    missing = False

    def replace(match: re.Match) -> str:
        nonlocal missing
        if match.group(1) not in context:
            missing = True
            return match.group(0)
        return str(context[match.group(1)])

    result = _PLACEHOLDER_RE.sub(replace, text)
    return None if missing or "{" in result else result


def _rendered(value: object, context: dict) -> object:
    if not isinstance(value, str) or "{{" not in value:
        return value
    return _substituted(value, context) or value


def _tile(src: str, background: str, width: int, height: int) -> str:
    return (
        f'<div class="tile" style="background:{background}">'
        f'<img src="{escape(src)}" width="{width}" height="{height}" alt=""></div>'
    )


def _render_role(
    role: str,
    logo: str,
    base: str,
    primary: str,
    out_dir: Path,
    project_root: Path,
) -> str:
    """Render one role's assets into ``out_dir/<role>`` and return its section.

    Args:
        role: Role to render.
        logo: Logo file.
        base: Hex base color of the palette.
        primary: Primary domain the role domain is rendered with.
        out_dir: Directory of the preview.
        project_root: Repository root, holding ``roles/``.

    Returns:
        The role's HTML section.
    """
    roles_dir = project_root / "roles"
    palette = build_palette(base)
    light, dark = palette["light"], palette["dark"]
    design_services = load_yaml_any(
        str(roles_dir / DESIGN_ROLE / ROLE_FILE_META_SERVICES)
    )
    services = load_yaml_any(str(roles_dir / role / ROLE_FILE_META_SERVICES)) or {}
    applications = {
        DESIGN_ROLE: {
            "services": {"design": {**design_services["design"], "logo": logo}}
        },
        role: {"services": services},
    }
    general = (
        load_yaml_any(str(project_root / "group_vars" / "all" / "00_general.yml")) or {}
    )
    branding = resolve_branding(applications, role, project_root)
    branding["title"] = _rendered(branding["title"], general)
    branding["name"] = _rendered(branding["name"], general)
    if branding["logo"] is False:
        return f"<h2>{escape(branding['name'])} · {role}</h2><p>logo replacement disabled</p>"
    monochrome = is_monochrome(branding["logo"])
    domain = role_domain(roles_dir, role, primary)
    assets = render_assets(
        branding["logo"],
        branding["title"],
        domain,
        light["--design-link"],
        light["--design-surface-1"],
        dark["--design-link"],
        dark["--design-surface-1"],
        light["--design-on-frame"],
        light["--design-frame"],
        branding["slots"],
    )
    role_dir = out_dir / role
    role_dir.mkdir(parents=True, exist_ok=True)
    for name, content in assets.items():
        (role_dir / name).write_bytes(content)
    favicon_day = _tile(f"{role}/favicon.ico", light["--design-surface-2"], 32, 32)
    favicon_night = _tile(f"{role}/favicon.ico", dark["--design-surface-2"], 32, 32)
    tiles = [
        f'<div class="slot"><b>favicon.ico</b><div class="pair">{favicon_day}{favicon_night}</div></div>'
    ]
    for slot, spec in branding["slots"].items():
        if f"{slot}.png" not in assets:
            continue
        width, height = spec["width"], spec["height"]
        if spec["frame"]:
            day_bg, night_bg = light["--design-frame"], dark["--design-frame"]
            night_src = f"{role}/{slot}.png"
        else:
            layout = choose_layout(
                width, height, spec["text_only"], bool(branding["title"])
            )
            night = render_png(
                None if layout == LAYOUT_TITLE else branding["logo"],
                str(branding["title"]),
                domain,
                dark["--design-link"],
                dark["--design-surface-1"],
                width,
                height,
                layout,
                dark["--design-link"] if monochrome else None,
            )
            (role_dir / f"{slot}.night.png").write_bytes(night)
            day_bg, night_bg = light["--design-surface-2"], dark["--design-surface-2"]
            night_src = f"{role}/{slot}.night.png"
        tiles.append(
            f'<div class="slot"><b>{escape(slot)}</b> {width}×{height}{" · frame" if spec["frame"] else ""}'
            f'<div class="pair">{_tile(f"{role}/{slot}.png", day_bg, width, height)}'
            f"{_tile(night_src, night_bg, width, height)}</div></div>"
        )
    return (
        f"<h2>{escape(branding['name'])} · {role} · {escape(domain)}</h2>"
        f'<div class="slots">{"".join(tiles)}</div>'
    )


def build_preview(
    logo: str,
    base: str,
    primary: str,
    roles: list[str],
    out_dir: Path,
    project_root: Path,
) -> Path:
    """Render every role's branding assets and an index page that shows them.

    Args:
        logo: Logo file.
        base: Hex base color of the palette.
        primary: Primary domain the role domains are rendered with.
        roles: Roles to render.
        out_dir: Directory the assets and ``index.html`` are written to.
        project_root: Repository root, holding ``roles/``.

    Returns:
        Path of the written ``index.html``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(len(roles), os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        sections = list(
            pool.map(
                _render_role,
                roles,
                [logo] * len(roles),
                [base] * len(roles),
                [primary] * len(roles),
                [out_dir] * len(roles),
                [project_root] * len(roles),
            )
        )
    monochrome = is_monochrome(logo)
    index = out_dir / "index.html"
    index.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Logo Preview</title><style>{_PAGE_CSS}</style></head><body>"
        f"<h1>Logo preview: {len(roles)} roles</h1>"
        f"<p>logo {escape(logo)} · base {escape(base)} · "
        f"{'monochrome, recolored per slot' if monochrome else 'own colors kept'} · "
        "left tile day, right tile night</p>"
        f"{''.join(sections)}</body></html>",
        encoding="utf-8",
    )
    return index
