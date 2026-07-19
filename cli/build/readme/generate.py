"""Generate / complete a role README from the template.

The generator owns only the sections it can derive from metadata:

  * **Cosmos**      – the mermaid diagram, from ``meta/services.yml``.
  * **Quick Setup** – the deploy commands, from the role id (invokable roles
                      only; removed from non-invokable roles).
  * **Credits**     – the fixed block, from ``meta/main.yml`` author.

Prose sections (Description, Overview, Features, Use Cases) cannot be
synthesised, so an existing README's prose is never rewritten. On a brand
new README the prose is emitted as fill-in placeholders.

Modes:
  * default   – add a managed section only when it is missing.
  * override  – regenerate every managed section, overwriting the current
                content in place (position is left untouched).
  * only      – restrict the run to a subset of the managed sections
                (e.g. ``("Cosmos",)`` for ``--update-cosmos``).
"""

from __future__ import annotations

import jinja2

from cli.build.readme import schema
from cli.build.readme.cosmos import derive_cosmos_mermaid
from cli.build.readme.sections import Readme, parse_readme
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.deploy import role_has_stack
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable
from utils.symbol_glossary import to_emoji

MANAGED_SECTIONS = ("Cosmos", "Quick Setup", "Credits")
_DEFAULT_AUTHOR = "Kevin Veen-Birkenbach"


def _is_invokable(role_name: str) -> bool:
    return _is_role_invokable(role_name, _get_invokable_paths())


def _render_template(ctx: dict) -> str:
    env = jinja2.Environment(  # noqa: S701 — renders Markdown, not HTML; escaping would corrupt it
        loader=jinja2.FileSystemLoader(str(schema.TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )
    return env.get_template(schema.TEMPLATE_NAME).render(**ctx)


def _role_author(role_dir) -> str:
    meta = load_yaml(role_dir / ROLE_FILE_META_MAIN, default_if_missing={})
    galaxy = meta.get("galaxy_info") if isinstance(meta, dict) else None
    author = galaxy.get("author") if isinstance(galaxy, dict) else None
    return author.strip() if isinstance(author, str) and author.strip() else _DEFAULT_AUTHOR


def _app_name(preamble: str, role_name: str) -> str:
    for line in preamble.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    entity = get_entity_name(role_name) or role_name
    return entity.replace("-", " ").title()


def _base_context(role_dir, role_name: str, app_name: str, *, invokable: bool) -> dict:
    return {
        "application_id": role_name,
        "application_name": app_name,
        "application_invokable": invokable,
        "application_url": "https://example.com/",
        "application_description": "is an application.",
        "application_overview": f"This role deploys {app_name}.",
        "application_features": [
            {"name": "Feature", "description": "Describe a capability."}
        ],
        "application_author": _role_author(role_dir),
        "application_is_host": not role_has_stack(role_dir),
        "cosmos_mermaid": derive_cosmos_mermaid(role_dir, role_name),
        "cosmos_legend": _cosmos_legend(),
    }


def _cosmos_legend() -> str:
    """Reading key rendered below the diagram; emojis come from the shared
    symbol glossary so a glyph means the same thing everywhere."""
    return (
        f"Solid `1:1` edges are fixed relationships; dashed `0..1` edges are "
        f"conditional (enabled only in matching deployments). Node markers "
        f"show the role's deploy modes ({to_emoji('host')} host, "
        f"{to_emoji('compose')} compose, {to_emoji('swarm')} swarm); "
        f"{to_emoji('disabled')} marks a service that is explicitly turned "
        f"off, and {to_emoji('role_dependency')} an Ansible role dependency "
        f"declared in `meta/main.yml`."
    )


def _managed_blocks(
    role_dir, role_name: str, app_name: str, *, invokable: bool
) -> dict[str, str]:
    rendered = _render_template(
        _base_context(role_dir, role_name, app_name, invokable=invokable)
    )
    parsed = parse_readme(rendered)
    return {
        title: block
        for title, block in parsed.sections
        if title in MANAGED_SECTIONS
    }


def _insert_managed(
    sections: list[tuple[str, str]], title: str, block: str, canonical: tuple[str, ...]
) -> None:
    """Insert ``title`` right after the last present section that canonically
    precedes it, so the required order holds without touching extras."""
    idx = canonical.index(title)
    preceding = set(canonical[:idx])
    anchor = -1
    for i, (existing_title, _) in enumerate(sections):
        if existing_title in preceding:
            anchor = i
    sections.insert(anchor + 1, (title, block))


def generate_readme(
    role_dir,
    role_name: str,
    *,
    override: bool = False,
    only: tuple[str, ...] = MANAGED_SECTIONS,
) -> tuple[str | None, list[str]]:
    """Return ``(new_text_or_None, actions)``.

    ``new_text_or_None`` is ``None`` when nothing changed.
    """
    readme_path = role_dir / ROLE_FILE_README
    canonical = schema.canonical_order()
    invokable = _is_invokable(role_name)

    if not readme_path.is_file():
        app_name = _app_name("", role_name)
        text = _render_template(
            _base_context(role_dir, role_name, app_name, invokable=invokable)
        )
        return text, ["create README.md from template"]

    original = read_text(str(readme_path))
    parsed = parse_readme(original)
    app_name = _app_name(parsed.preamble, role_name)
    managed = _managed_blocks(role_dir, role_name, app_name, invokable=invokable)

    sections = list(parsed.sections)
    present = {title for title, _ in sections}
    actions: list[str] = []

    for title in MANAGED_SECTIONS:
        if title not in only:
            continue
        if title not in managed:
            if title in present:
                sections = [(t, b) for t, b in sections if t != title]
                actions.append(f"remove {title}")
            continue
        block = managed[title]
        if title in present:
            if override:
                sections = [(t, block if t == title else b) for t, b in sections]
                actions.append(f"override {title}")
        else:
            _insert_managed(sections, title, block, canonical)
            actions.append(f"add {title}")

    new_text = Readme(parsed.preamble, sections).render()
    if new_text == original:
        return None, []
    return new_text, actions


def role_dirs(roles_root=None) -> list:
    root = roles_root or (PROJECT_ROOT / "roles")
    return sorted(p for p in root.iterdir() if p.is_dir())
