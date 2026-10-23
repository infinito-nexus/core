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
                (e.g. ``("Architecture",)`` for ``--update-architecture``).
"""

from __future__ import annotations

import jinja2

from cli.build.docs.readme import schema
from cli.build.docs.readme.architecture import derive_architecture_page
from cli.build.docs.readme.sections import Readme, parse_readme
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.meta.identity import by_name, profile_url
from utils.roles.deploy import role_has_stack
from utils.roles.entity.name import entity_name
from utils.licensing.roles import OWN_LICENSE, declared
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_README,
)
from utils.roles.meta_lookup import get_role_guide_companions
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable
from utils.software import SOFTWARE_REPOSITORY, deploy_image

MANAGED_SECTIONS = ("Architecture", "Quick Setup", "Credits")
_DEFAULT_AUTHOR = "Kevin Veen-Birkenbach"


def _is_invokable(role_name: str) -> bool:
    return _is_role_invokable(role_name, _get_invokable_paths())


def _render_template(ctx: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(schema.TEMPLATE_DIR)),
        keep_trailing_newline=True,
        autoescape=jinja2.select_autoescape(),
    )
    return env.get_template(schema.TEMPLATE_NAME).render(**ctx)


def _role_author(role_dir) -> str:
    meta = load_yaml(role_dir / ROLE_FILE_META_MAIN, default_if_missing={})
    galaxy = meta.get("galaxy_info") if isinstance(meta, dict) else None
    author = galaxy.get("author") if isinstance(galaxy, dict) else None
    return (
        author.strip()
        if isinstance(author, str) and author.strip()
        else _DEFAULT_AUTHOR
    )


def _app_name(preamble: str, role_name: str) -> str:
    for line in preamble.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    entity = entity_name(role_name) or role_name
    return entity.replace("-", " ").title()


def _role_yaml_mentions(role_dir, needle: str, *subdirs: str) -> bool:
    """Whether a YAML file below one of the role's ``subdirs`` contains ``needle``.

    Args:
        role_dir: the role's directory.
        needle: the text to look for, typically a variable path.
        subdirs: role subdirectories to search, e.g. ``"tasks"``.
    """
    return any(
        needle in read_text(str(path))
        for subdir in subdirs
        for path in sorted((role_dir / subdir).rglob("*.yml"))
    )


def _needs_clearnet_resolver(role_dir) -> bool:
    """Whether the role refuses to deploy without ``networks.internet.dns``.

    Only the inventories under ``inventories/development/`` set that value, so a
    role asserting it has to name it in the block an operator copies, or the
    documented deploy aborts on the assert.
    """
    return _role_yaml_mentions(role_dir, "networks.internet.dns", "tasks")


def _needs_service_provider_country(role_dir) -> bool:
    """Whether the role deploys with ``service_provider.company.address.country``.

    The group default is a placeholder no country list knows, so a role whose
    tasks or vars consume it has to name it in the block an operator copies, or
    the documented deploy aborts on the unknown country.
    """
    return _role_yaml_mentions(
        role_dir, "service_provider.company.address.country", "tasks", "vars"
    )


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
        "application_author_url": profile_url(
            by_name().get(_role_author(role_dir), "")
        ),
        "application_is_host": not role_has_stack(role_dir),
        "application_needs_clearnet_resolver": _needs_clearnet_resolver(role_dir),
        "application_deploy_ids": ",".join(
            [role_name, *get_role_guide_companions(role_dir, role_name=role_name)]
        ),
        "software_repository": SOFTWARE_REPOSITORY,
        "application_deploy_image": deploy_image(),
        "application_license": _software_license(role_dir),
        "application_needs_service_provider_country": _needs_service_provider_country(
            role_dir
        ),
    }


def _software_license(role_dir) -> dict | None:
    """Return the licence of the software the role deploys, or None.

    The single source is ``meta/license.yml``; the README states it rather
    than holding a second copy, because the licence of the deployed software
    is a different fact from this repository's own licence that Credits names.

    Args:
        role_dir: the role directory.
    """
    entry = declared(role_dir)
    if entry is None or not entry.spdx:
        return None
    return {
        "spdx": entry.spdx,
        "source": entry.url,
        "commercial": entry.context.commercial,
        "duties": entry.context.duties,
        "is_own": entry.spdx == OWN_LICENSE,
    }


def generate_architecture_page(role_dir, role_name: str) -> str | None:
    """Return the ARCHITECTURE.md body, or None when the role gets no page.

    Args:
        role_dir: the role directory.
        role_name: the role identifier.

    Returns:
        The page, titled after the committed README so both documents name the
        application the same way, or None for a role that is not invokable.
    """
    if not _is_invokable(role_name):
        return None
    readme_path = role_dir / ROLE_FILE_README
    preamble = (
        parse_readme(read_text(str(readme_path))).preamble
        if readme_path.is_file()
        else ""
    )
    return derive_architecture_page(
        role_dir, role_name, _app_name(preamble, role_name)
    )


def _managed_blocks(
    role_dir, role_name: str, app_name: str, *, invokable: bool
) -> dict[str, str]:
    rendered = _render_template(
        _base_context(role_dir, role_name, app_name, invokable=invokable)
    )
    parsed = parse_readme(rendered)
    return {
        title: block for title, block in parsed.sections if title in MANAGED_SECTIONS
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
