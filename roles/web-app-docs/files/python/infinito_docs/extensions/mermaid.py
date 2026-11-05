"""Render ```` ```mermaid ```` fences as diagrams instead of code blocks.

The fence is replaced by a ``<pre class="mermaid">`` that the self-hosted
``mermaid.min.js`` picks up, so no directive and no inline script are needed
and the fence keeps rendering as source in every non-HTML builder.
"""

from __future__ import annotations

import html

from docutils import nodes
from sphinx.transforms.post_transforms import SphinxPostTransform

LANGUAGE = "mermaid"


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
                f'<pre class="mermaid">{html.escape(node.astext())}</pre>',
                format="html",
            )
            node.replace_self(diagram)


def setup(app):
    app.add_post_transform(MermaidFences)
    app.add_js_file("js/mermaid.min.js")
    app.add_js_file("js/mermaid-init.js")
    return {"version": "1.0", "parallel_read_safe": True}
