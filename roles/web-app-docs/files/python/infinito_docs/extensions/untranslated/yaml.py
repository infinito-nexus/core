from __future__ import annotations

from docutils import nodes
from sphinx.transforms import SphinxTransform

YAML_SUFFIXES = (".yml", ".yaml")


class UntranslatedYaml(SphinxTransform):
    """Mark every text node of a page rendered from a YAML file untranslatable."""

    default_priority = 5

    def apply(self, **kwargs) -> None:
        if not str(self.document.get("source", "")).endswith(YAML_SUFFIXES):
            return
        for node in self.document.findall(nodes.TextElement):
            node["translatable"] = False


def setup(app):
    app.add_transform(UntranslatedYaml)
    return {"version": "1.0", "parallel_read_safe": True}
