from __future__ import annotations

import importlib
import os
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

_PAGE = "<html><body><!-- built by sphinx --><p>kept</p></body></html>"


class _App:
    def __init__(self, listeners=()) -> None:
        self.connected = []
        self.disconnected = []
        self.events = SimpleNamespace(listeners={"build-finished": list(listeners)})

    def connect(self, event, handler) -> None:
        self.connected.append((event, handler))

    def disconnect(self, listener_id) -> None:
        self.disconnected.append(listener_id)


class _InlinePool:
    def __init__(self, processes, initializer, initargs) -> None:
        self.processes = processes
        initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info) -> None:
        return None

    def imap_unordered(self, func, items, **_kwargs):
        return map(func, items)


class _InlineContext:
    def __init__(self) -> None:
        self.methods = []
        self.pools = []

    def __call__(self, method):
        self.methods.append(method)
        return self

    def Pool(self, processes, initializer, initargs):  # noqa: N802
        pool = _InlinePool(processes, initializer, initargs)
        self.pools.append(pool)
        return pool


def _built_app(directory, theme_options):
    return SimpleNamespace(
        builder=SimpleNamespace(
            name="html",
            get_outfilename=lambda doc: str(Path(directory) / f"{doc}.html"),
        ),
        config=SimpleNamespace(html_theme_options=theme_options),
        env=SimpleNamespace(awesome_changed_docs=["a", "b", "c"]),
        parallel=1,
        verbosity=0,
    )


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

    def test_a_worker_rewrites_a_page_with_the_theme_options_alone(self) -> None:
        with TemporaryDirectory() as td:
            page = Path(td) / "page.html"
            page.write_text(_PAGE, encoding="utf-8")

            parallel_postprocess._adopt_theme_options({"awesome_headerlinks": True})
            returned = parallel_postprocess._postprocess_one(str(page))
            rewritten = page.read_text(encoding="utf-8")  # nocheck: cache-read

        self.assertEqual(returned, str(page))
        self.assertNotIn("built by sphinx", rewritten)
        self.assertIn("<p>kept</p>", rewritten)
        self.assertEqual(
            parallel_postprocess.logos.get_theme_options(
                parallel_postprocess._STATE["app"]
            ),
            {"awesome_headerlinks": True},
        )

    def test_the_pool_follows_the_postprocess_jobs_not_the_sphinx_jobs(self) -> None:
        context = _InlineContext()
        with TemporaryDirectory() as td:
            pages = [Path(td) / f"{doc}.html" for doc in ("a", "b", "c")]
            for page in pages:
                page.write_text(_PAGE, encoding="utf-8")
            app = _built_app(td, {"awesome_external_links": False})

            with (
                patch.dict(os.environ, {parallel_postprocess.JOBS_ENV: "3"}),
                patch.object(parallel_postprocess, "get_context", context),
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

        self.assertEqual(untouched, [_PAGE] * 3)
        self.assertTrue(all("built by sphinx" not in page for page in rewritten))
        self.assertTrue(all("<p>kept</p>" in page for page in rewritten))
        self.assertEqual(context.methods, ["spawn"])
        self.assertEqual([pool.processes for pool in context.pools], [3])
        self.assertEqual(
            parallel_postprocess._STATE["app"].config.html_theme_options,
            {"awesome_external_links": False},
        )


if __name__ == "__main__":
    unittest.main()
