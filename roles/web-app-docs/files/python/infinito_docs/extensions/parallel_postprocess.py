from __future__ import annotations

import os
from multiprocessing import get_context
from types import SimpleNamespace

from sphinx.util.display import status_iterator
from sphinxawesome_theme import logos, postprocess

JOBS_ENV = "DOCS_POSTPROCESS_JOBS"
_STATE = {}


def _adopt_theme_options(theme_options):
    """
    Args:
        theme_options: the theme options the parent's builder resolved.
    """
    _STATE["app"] = SimpleNamespace(
        builder=None, config=SimpleNamespace(html_theme_options=theme_options)
    )


def _postprocess_one(path):
    postprocess.modify_html(path, _STATE["app"])
    return path


def parallel_post_process_html(app, exc):
    """
    Args:
        app: the Sphinx application; only its theme options reach the workers.
        exc: the exception that ended the build, if any.
    """
    if exc is not None or app.builder.name not in {"html", "dirhtml"}:
        return
    files = [app.builder.get_outfilename(doc) for doc in app.env.awesome_changed_docs]
    with get_context("spawn").Pool(
        int(os.environ[JOBS_ENV]),
        initializer=_adopt_theme_options,
        initargs=(dict(logos.get_theme_options(app)),),
    ) as pool:
        for _ in status_iterator(
            pool.imap_unordered(_postprocess_one, files, chunksize=8),
            "postprocess html... ",
            "brown",
            len(files),
            app.verbosity,
        ):
            pass


def use_parallel_postprocess(app):
    for listener in list(app.events.listeners["build-finished"]):
        if listener.handler is postprocess.post_process_html:
            app.disconnect(listener.id)
    app.connect("build-finished", parallel_post_process_html)


def setup(app):
    app.connect("builder-inited", use_parallel_postprocess)
    return {"version": "0.1", "parallel_read_safe": True}
