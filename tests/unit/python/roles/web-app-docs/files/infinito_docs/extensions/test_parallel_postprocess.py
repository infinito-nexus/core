from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

parallel_postprocess = importlib.import_module(
    "infinito_docs.extensions.parallel_postprocess"
)


class _App:
    def __init__(self, listeners=()) -> None:
        self.connected = []
        self.disconnected = []
        self.events = SimpleNamespace(listeners={"build-finished": list(listeners)})

    def connect(self, event, handler) -> None:
        self.connected.append((event, handler))

    def disconnect(self, listener_id) -> None:
        self.disconnected.append(listener_id)


def _mark_done(path, app) -> None:
    Path(path).write_text(f"done by {app.builder.name}", encoding="utf-8")


class TestParallelPostprocess(unittest.TestCase):
    def test_setup_swaps_the_postprocess_once_the_builder_exists(self) -> None:
        app = _App()
        self.assertTrue(parallel_postprocess.setup(app)["parallel_read_safe"])
        self.assertEqual(
            app.connected,
            [("builder-inited", parallel_postprocess.use_parallel_postprocess)],
        )

    def test_theme_postprocess_is_replaced_by_the_parallel_one(self) -> None:
        theme = SimpleNamespace(
            id=7, handler=parallel_postprocess.postprocess.post_process_html
        )
        other = SimpleNamespace(id=8, handler=print)
        app = _App([theme, other])

        parallel_postprocess.use_parallel_postprocess(app)

        self.assertEqual(app.disconnected, [7])
        self.assertEqual(
            app.connected,
            [("build-finished", parallel_postprocess.parallel_post_process_html)],
        )

    def test_every_changed_page_is_rewritten_and_failed_builds_are_left(self) -> None:
        with TemporaryDirectory() as td:
            pages = [Path(td) / f"{doc}.html" for doc in ("a", "b", "c")]
            for page in pages:
                page.write_text("raw", encoding="utf-8")
            app = SimpleNamespace(
                builder=SimpleNamespace(
                    name="html",
                    get_outfilename=lambda doc: str(Path(td) / f"{doc}.html"),
                ),
                env=SimpleNamespace(awesome_changed_docs=["a", "b", "c"]),
                parallel=2,
                verbosity=0,
            )

            with patch.object(
                parallel_postprocess.postprocess, "modify_html", _mark_done
            ):
                parallel_postprocess.parallel_post_process_html(
                    app, RuntimeError("build failed")
                )
                untouched = [read_text(str(page)) for page in pages]
                parallel_postprocess.parallel_post_process_html(app, None)

            rewritten = [
                page.read_text(encoding="utf-8")  # nocheck: cache-read
                for page in pages
            ]

        self.assertEqual(untouched, ["raw"] * 3)
        self.assertEqual(rewritten, ["done by html"] * 3)


if __name__ == "__main__":
    unittest.main()
