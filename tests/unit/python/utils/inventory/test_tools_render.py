from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text
from utils.inventory import tools

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
            template = root / tools.TEMPLATE
            template.parent.mkdir(parents=True)
            template.write_text(TEMPLATE, encoding="utf-8")
            with patch.object(tools, "models_dir", return_value=MARKUP):
                rendered = read_text(str(tools.render(root, ["en", "de"])))
        self.assertIn(f'models: "{MARKUP}"', rendered)
        self.assertIn("languages: de,en", rendered)
        self.assertIn(f"key: {tools.API_KEY}", rendered)
        self.assertIn("{{ ansible_expression }}", rendered)
        self.assertNotIn("&lt;", rendered)
        self.assertNotIn("&amp;", rendered)


if __name__ == "__main__":
    unittest.main()
