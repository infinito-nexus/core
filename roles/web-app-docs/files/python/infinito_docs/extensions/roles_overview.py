from __future__ import annotations

import json
from pathlib import Path

from docutils import nodes
from docutils.parsers.rst import Directive
from sphinx.util import logging

logger = logging.getLogger(__name__)

OVERVIEW_FILE = Path("generated") / "roles_overview.json"


class RolesOverviewDirective(Directive):
    has_content = False

    def run(self):
        overview = Path(self.state.document.settings.env.srcdir) / OVERVIEW_FILE
        if not overview.is_file():
            logger.warning("Roles overview not generated: %s", overview)
            return [
                self.state.document.reporter.error(
                    "Roles overview not generated.", line=self.lineno
                )
            ]

        container = nodes.container()
        categories = json.loads(overview.read_text(encoding="utf-8"))
        for tag, roles in sorted(categories.items(), key=lambda item: item[0].lower()):
            category_section = nodes.section(ids=[nodes.make_id(tag)])
            category_section += nodes.title(text=tag)
            for role in sorted(roles, key=lambda role: role["name"].lower()):
                role_section = nodes.section(ids=[nodes.make_id(role["title"])])
                role_title = nodes.title()
                role_title += nodes.reference(text=role["title"], refuri=role["link"])
                role_section += role_title
                if role["description"]:
                    role_section += nodes.paragraph(text=role["description"])
                category_section += role_section
            container += category_section
        return [container]


def setup(app):
    app.add_directive("roles-overview", RolesOverviewDirective)
    return {"version": "0.1", "parallel_read_safe": True}
