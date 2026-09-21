from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docutils import nodes
from docutils.utils import new_document

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

with patch.object(sys, "argv", ["sphinx-build"]):
    conf = importlib.import_module("infinito_docs.conf")


class _App:
    def __init__(self) -> None:
        self.connected = []
        self.registry = SimpleNamespace(domains={})

    def connect(self, event, handler) -> None:
        self.connected.append((event, handler))


class TestConf(unittest.TestCase):
    def test_every_local_extension_resolves(self) -> None:
        local = [name for name in conf.extensions if name.startswith("infinito_docs.")]
        self.assertEqual(len(local), 5)
        for name in local:
            self.assertTrue(hasattr(importlib.import_module(name), "setup"), name)

    def test_templates_and_theme_point_at_shipped_files(self) -> None:
        self.assertEqual(conf.html_theme, "sphinxawesome_theme")
        for template in conf.html_sidebars["**"]:
            self.assertTrue(Path(conf.templates_path[0], template).is_file(), template)

    def test_every_documented_suffix_is_parsed(self) -> None:
        self.assertEqual(set(conf.source_suffix), {".md", ".rst", ".yml", ".yaml"})

    def test_asset_references_are_rewritten_to_static(self) -> None:
        doctree = new_document("index")
        image = nodes.image(uri="assets/img/logo.png")
        raw = nodes.raw("", '<img src="assets/img/favicon.ico">', format="html")
        doctree += [image, raw]

        conf.replace_assets_in_doctree(None, doctree, "index")

        self.assertEqual(image["uri"], "_static/img/logo.png")
        rewritten = next(iter(doctree.findall(nodes.raw))).astext()
        self.assertIn("_static/img/favicon.ico", rewritten)

    def test_setup_hooks_the_asset_rewrite(self) -> None:
        app = _App()
        self.assertTrue(conf.setup(app)["parallel_read_safe"])
        self.assertIn(
            ("doctree-resolved", conf.replace_assets_in_doctree), app.connected
        )

    def test_built_version_comes_from_the_environment(self) -> None:
        with patch.dict("os.environ", {"DOCS_VERSION": "v1.2.3"}):
            reloaded = importlib.reload(conf)
        self.assertEqual(reloaded.html_context, {"docs_version": "v1.2.3"})
        self.assertIn("versions.html", reloaded.html_sidebars["**"])


if __name__ == "__main__":
    unittest.main()
