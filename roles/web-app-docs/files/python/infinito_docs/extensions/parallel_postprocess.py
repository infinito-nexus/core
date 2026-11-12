from __future__ import annotations

from multiprocessing import get_context

from sphinx.util.display import status_iterator
from sphinxawesome_theme import postprocess

_STATE = {}


def _postprocess_one(path):
    postprocess.modify_html(path, _STATE["app"])
    return path


def parallel_post_process_html(app, exc):
    """Run the theme's per-page HTML rewrite on ``-j`` forked workers.

    Args:
        app: the Sphinx application; forked workers inherit it.
        exc: the exception that ended the build, if any.
    """
    if exc is not None or app.builder.name not in {"html", "dirhtml"}:
        return
    files = [app.builder.get_outfilename(doc) for doc in app.env.awesome_changed_docs]
    _STATE["app"] = app
    with get_context("fork").Pool(max(app.parallel, 1)) as pool:
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
