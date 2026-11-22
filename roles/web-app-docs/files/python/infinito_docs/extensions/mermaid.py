"""Render ```` ```mermaid ```` fences as diagrams instead of code blocks.

The fence is replaced by a ``<pre class="mermaid">`` that the self-hosted
``mermaid.min.js`` picks up, so no directive and no inline script are needed
and the fence keeps rendering as source in every non-HTML builder.

The scripts load only on pages that draw a diagram: ``mermaid.min.js`` is a
1.6 MB synchronous script, and on every other page it would only hold back
``DOMContentLoaded`` until it has crossed the wire.
"""

from __future__ import annotations

import html

from docutils import nodes
from sphinx.transforms.post_transforms import SphinxPostTransform

LANGUAGE = "mermaid"
OPENING = '<pre class="mermaid">'
SCRIPTS = ("js/mermaid.min.js", "js/mermaid-init.js")


class MermaidFences(SphinxPostTransform):
    """Turn every mermaid literal block of an HTML page into a raw diagram."""

    default_priority = 400
    formats = ("html",)

    def run(self, **kwargs) -> None:
        for node in list(self.document.findall(nodes.literal_block)):
            if node.get("language") != LANGUAGE:
                continue
            diagram = nodes.raw(
                "",
                f"{OPENING}{html.escape(node.astext())}</pre>",
                format="html",
            )
            node.replace_self(diagram)


def holds_diagram(doctree) -> bool:
    """Tell whether a resolved doctree draws a mermaid diagram.

    Args:
        doctree: the page's doctree after the post-transforms, or ``None``
            for a page Sphinx generates without one.

    Returns:
        ``True`` when a raw node opens a mermaid ``<pre>``.
    """
    if doctree is None:
        return False
    return any(node.astext().startswith(OPENING) for node in doctree.findall(nodes.raw))


def add_diagram_scripts(app, pagename, templatename, context, doctree) -> None:
    """Add the mermaid scripts to the page being rendered if it draws a diagram.

    Args:
        app: the Sphinx application.
        pagename: name of the page being rendered.
        templatename: template the page renders with.
        context: the page's template context.
        doctree: the page's resolved doctree, or ``None``.
    """
    if holds_diagram(doctree):
        for script in SCRIPTS:
            app.add_js_file(script)


def setup(app):
    app.add_post_transform(MermaidFences)
    app.connect("html-page-context", add_diagram_scripts)
    return {"version": "1.0", "parallel_read_safe": True}
