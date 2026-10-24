"""Ship every remote image a page embeds with the site instead of hotlinking it."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import requests
from docutils import nodes
from sphinx.util import logging

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 30
CACHE_DIR = "remote-images"


def fetch_image(uri: str, cache: Path) -> Path | None:
    """Download ``uri`` into ``cache`` under a suffix that names its type.

    Args:
        uri: absolute URL of the image.
        cache: directory the downloads of this build are kept in.

    Returns:
        The local copy, or None when the host does not answer with an image.
    """
    stem = hashlib.sha256(uri.encode()).hexdigest()
    for existing in cache.glob(f"{stem}.*"):
        return existing
    try:
        response = requests.get(uri, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("remote image %s not fetched: %s", uri, exc)
        return None
    mimetype = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    suffix = (
        mimetypes.guess_extension(mimetype) if mimetype.startswith("image/") else None
    )
    if not suffix:
        logger.warning("remote image %s answered %r instead of an image", uri, mimetype)
        return None
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{stem}{suffix}"
    target.write_bytes(response.content)
    return target


def localize_remote_images(app, doctree, docname) -> None:
    """Point every remote image of ``docname`` at a copy the site serves.

    Args:
        app: the Sphinx application.
        doctree: the resolved doctree of the page.
        docname: the page being written.
    """
    if app.builder.format != "html":
        return
    cache = Path(app.doctreedir) / CACHE_DIR
    for node in list(doctree.findall(nodes.image)):
        uri = node["uri"]
        if not urlsplit(uri).netloc:
            continue
        local = fetch_image(uri, cache)
        if local is None:
            node.replace_self(nodes.Text(node.get("alt", "")))
            continue
        node["uri"] = str(local)
        node["candidates"] = {"*": str(local)}
        app.env.images.add_file(docname, str(local))


def setup(app):
    app.connect("doctree-resolved", localize_remote_images)
    return {"version": "1.0", "parallel_read_safe": True}
