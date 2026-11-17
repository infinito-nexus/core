from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.env.handlers.infinito.cache.paths import BASE_KEY
from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY
from utils.inventory import tools_vars

MARKUP = "/models/<a & 'b'>\""
TEMPLATE = (
    'models: "[[ models_dir ]]"\n'
    "languages: [[ load_only | join(',') ]]\n"
    "key: [[ s1_api_key ]]\n"
    "[% raw %]{{ ansible_expression }}[% endraw %]\n"
)


class TestRender(unittest.TestCase):
    def test_the_yaml_lane_renders_without_html_escaping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / tools_vars.TEMPLATE
            template.parent.mkdir(parents=True)
            template.write_text(TEMPLATE, encoding="utf-8")
            lane = {BASE_KEY: "/srv/cache", MODELS_KEY: MARKUP}
            rendered = read_text(str(tools_vars.render(root, ["en", "de"], lane)))
        self.assertIn(f'models: "{MARKUP}"', rendered)
        self.assertIn("languages: de,en", rendered)
        self.assertIn(f"key: {tools_vars.API_KEY}", rendered)
        self.assertIn("{{ ansible_expression }}", rendered)
        self.assertNotIn("&lt;", rendered)
        self.assertNotIn("&amp;", rendered)


if __name__ == "__main__":
    unittest.main()
