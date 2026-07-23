"""Derive the role-README section schema from the Jinja template.

``templates/roles/README.md.j2.tmpl`` is the single source of truth. The
required sections are the H2s the template emits with no optional context;
the optional sections are the extra H2s that appear once every
``{% if ... %}``-guarded variable is supplied. Rendering the template both
ways and diffing the H2 sets keeps the lint and the generator in lock-step
with the template.
"""

from __future__ import annotations

import functools

import jinja2

from cli.build.readme.sections import h2_titles
from utils.cache.files import PROJECT_ROOT

TEMPLATE_DIR = PROJECT_ROOT / "templates" / "roles"
TEMPLATE_NAME = "README.md.j2.tmpl"

_REQUIRED_CTX: dict = {
    "application_id": "web-app-example",
    "application_name": "Example",
    "application_url": "https://example.com/",
    "application_description": "is an example application.",
    "application_overview": "This role deploys the example application.",
    "application_features": [{"name": "Example", "description": "An example feature."}],
    "application_author": "Kevin Veen-Birkenbach",
    "cosmos_mermaid": 'flowchart LR\n    a["a"] --> b["b"]',
}

_OPTIONAL_CTX: dict = {
    "application_invokable": True,
    "cosmos_intro": "Example cosmos intro.",
    "application_author_url": "https://www.veen.world",
    "application_use_cases": "Example use case.",
    "application_developer_notes": [{"file": "Administration.md", "description": "notes."}],
    "application_further_resources": [{"label": "Example", "url": "https://example.com/"}],
}


def _render(ctx: dict) -> str:
    env = jinja2.Environment(  # noqa: S701 — renders Markdown, not HTML; escaping would corrupt it
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )
    return env.get_template(TEMPLATE_NAME).render(**ctx)


def render_required() -> str:
    return _render(dict(_REQUIRED_CTX))


def render_full() -> str:
    return _render({**_REQUIRED_CTX, **_OPTIONAL_CTX})


@functools.lru_cache(maxsize=1)
def required_sections() -> tuple[str, ...]:
    """H2 titles the template emits without any optional context (mandatory)."""
    return tuple(h2_titles(render_required()))


@functools.lru_cache(maxsize=1)
def canonical_order() -> tuple[str, ...]:
    """Full H2 order (required + optional) as the template lays them out."""
    return tuple(h2_titles(render_full()))


@functools.lru_cache(maxsize=1)
def optional_sections() -> tuple[str, ...]:
    required = set(required_sections())
    return tuple(title for title in canonical_order() if title not in required)


def credits_heading() -> str:
    """The last required section (Credits by convention)."""
    return required_sections()[-1]
