from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babel.messages.pofile import read_po

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

from infinito_docs.identity import docs_sphinx_identity  # noqa: E402

DOCS_SPHINX_IDENTITY = docs_sphinx_identity(PROJECT_ROOT)

i18n = importlib.import_module("infinito_docs.i18n")


class TestExtract(unittest.TestCase):
    def test_messages_land_in_one_docs_template_without_yaml_pages(self) -> None:
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "index.rst").write_text(
                "Title\n=====\n\nThe platform welcomes you.\n\n.. toctree::\n\n   config\n",
                encoding="utf-8",
            )
            (src / "config.yml").write_text(
                "name: sys-stk-front-proxy\n", encoding="utf-8"
            )
            images = src / "assets" / "img"
            images.mkdir(parents=True)
            (images / "favicon.ico").write_bytes(b"")
            output = Path(tmp) / "docs.pot"

            with (
                patch.object(i18n, "generate_commands", lambda src: []),
                patch.dict("os.environ", DOCS_SPHINX_IDENTITY),
            ):
                i18n.extract(src, output, 1)

            with output.open("rb") as handle:
                messages = {message.id for message in read_po(handle) if message.id}

        self.assertIn("The platform welcomes you.", messages)
        self.assertNotIn("name: sys-stk-front-proxy", messages)


if __name__ == "__main__":
    unittest.main()
