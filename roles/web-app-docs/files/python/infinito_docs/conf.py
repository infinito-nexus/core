from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from docutils import nodes
from pygments.lexers.templates import DjangoLexer
from sphinx.domains.python import PythonDomain
from sphinx.highlighting import lexers

logging.basicConfig(
    level=logging.DEBUG if {"-v", "--verbose"} & set(sys.argv) else logging.INFO
)
logger = logging.getLogger(__name__)

CONF_DIR = Path(__file__).resolve().parent

templates_path = [str(CONF_DIR / "templates")]
html_static_path = [str(CONF_DIR / "assets")]

project = "Infinito.Nexus - Cyber Master Infrastructure Solution"
copyright = "2025, Kevin Veen-Birkenbach"  # noqa: A001
author = "Kevin Veen-Birkenbach"

lexers["jinja"] = DjangoLexer()
lexers["j2"] = DjangoLexer()

exclude_patterns = ["docs/build", "venv", "venv/**"]

html_theme = "sphinxawesome_theme"
html_sidebars = {
    "**": ["logo.html", "versions.html", "languages.html", "structure.html"]
}
html_context = {"docs_version": os.environ.get("DOCS_VERSION", "")}
html_favicon = "assets/img/favicon.ico"
html_theme_options = {
    "show_prev_next": False,
    "logo_light": "assets/img/logo.png",
    "logo_dark": "assets/img/logo.png",
}

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".yml": "yaml",
    ".yaml": "yaml",
}

extensions = [
    "myst_parser",
    "infinito_docs.extensions.local.file_headings",
    "infinito_docs.extensions.local.subfolders",
    "infinito_docs.extensions.roles_overview",
    "infinito_docs.extensions.markdown_include",
    "infinito_docs.extensions.parallel_postprocess",
    "infinito_docs.extensions.untranslated_yaml",
    "infinito_docs.extensions.yaml_source",
    "infinito_docs.extensions.directory_readme",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
]

autosummary_generate = True

locale_dirs = ["locale"]
gettext_compact = "docs"
gettext_location = False

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 6


def replace_assets_in_doctree(app, doctree, docname):
    for node in doctree.findall(nodes.image):
        if "assets/" in node["uri"]:
            node["uri"] = node["uri"].replace("assets/", "_static/")
            logger.info("Replaced image URI in %s: %s", docname, node["uri"])

    for node in doctree.findall(nodes.raw):
        if node.get("format") == "html" and "assets/" in node.astext():
            rewritten = node.astext().replace("assets/", "_static/")
            node.children = [nodes.raw("", rewritten, format="html")]
            logger.info("Replaced raw HTML assets in %s.", docname)


def setup(app):
    app.connect("doctree-resolved", replace_assets_in_doctree)

    python_domain = app.registry.domains.get(PythonDomain.name)
    if python_domain is not None:
        directive = python_domain.directives.get("currentmodule")
        if directive is not None:
            directive.optional_arguments = 10
    return {"version": "1.0", "parallel_read_safe": True}
