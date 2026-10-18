from __future__ import annotations

import logging
from pathlib import Path

from infinito_docs.extensions.nav_utils import (
    DEFAULT_MAX_NAV_DEPTH,
    MAX_HEADING_LEVEL,
    extract_headings_from_file,
    group_headings,
    sort_tree,
)

logger = logging.getLogger(__name__)


def add_local_file_headings(app, pagename, templatename, context, doctree):
    directory = pagename.rpartition("/")[0]
    abs_dir = Path(app.srcdir) / directory
    if not abs_dir.is_dir():
        logger.warning("Directory %s not found for page %s.", abs_dir, pagename)
        context["local_md_headings"] = []
        return

    files = [path.name for path in abs_dir.iterdir() if path.suffix in {".md", ".rst"}]
    if "index.rst" in {name.lower() for name in files}:
        files = [name for name in files if name.lower() != "readme.md"]

    items = []
    for name in files:
        stem = Path(name).stem
        items.extend(
            {
                "level": heading["level"],
                "text": heading["text"],
                "link": f"{directory}/{stem}" if directory else stem,
                "anchor": heading["anchor"],
                "priority": 0 if stem.lower() == "index" else 1,
                "filename": stem,
            }
            for heading in extract_headings_from_file(
                abs_dir / name, max_level=MAX_HEADING_LEVEL
            )
        )

    tree = group_headings(items)
    sort_tree(tree)
    context["local_md_headings"] = tree


def setup(app):
    app.add_config_value("local_nav_max_depth", DEFAULT_MAX_NAV_DEPTH, "env")
    app.connect("html-page-context", add_local_file_headings)
    return {"version": "0.1", "parallel_read_safe": True}
