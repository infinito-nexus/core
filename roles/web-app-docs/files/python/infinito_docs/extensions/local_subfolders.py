from __future__ import annotations

import copy
from functools import cache
from pathlib import Path

from .nav_utils import MAX_HEADING_LEVEL, extract_headings_from_file

CANDIDATES = ("index.rst", "readme.md", "main.rst")


def _join(base_url, name):
    return f"{base_url}/{name}" if base_url else name


def _title(path, fallback):
    headings = extract_headings_from_file(path, max_level=MAX_HEADING_LEVEL)
    return headings[0]["text"] if headings else fallback


def collect_folder_tree(dir_path, base_url):
    """Return the navigation tree below ``dir_path``.

    Args:
        dir_path: directory to walk.
        base_url: link prefix of ``dir_path`` inside the site.

    Returns:
        ``{"text", "link", "children", "filename"}``, or ``None`` for a hidden
        directory or one without an ``index.rst``, ``readme.md`` or
        ``main.rst`` to title it.
    """
    directory = Path(dir_path)
    if directory.name.startswith("."):
        return None

    files = [
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.suffix in {".md", ".rst"}
    ]
    rep_file = next(
        (
            name
            for candidate in CANDIDATES
            for name in files
            if name.lower() == candidate
        ),
        None,
    )
    if rep_file is None:
        return None

    children = [
        {
            "level": 1,
            "text": _title(directory / name, name),
            "link": _join(base_url, Path(name).stem),
            "anchor": "",
            "priority": 1,
            "filename": name,
        }
        for name in sorted(files, key=str.lower)
        if name.lower() not in CANDIDATES
    ]
    for sub in sorted(directory.iterdir(), key=lambda path: path.name.lower()):
        if sub.is_dir() and not sub.name.startswith("."):
            subtree = collect_folder_tree(sub, _join(base_url, sub.name))
            if subtree:
                children.append(subtree)

    return {
        "text": _title(directory / rep_file, directory.name),
        "link": _join(base_url, Path(rep_file).stem),
        "children": children,
        "filename": directory.name,
    }


def mark_current(node, active):
    link = node.get("link", "").rstrip("/")
    active = active.rstrip("/")
    is_current = bool(link) and (active == link or active.startswith(link + "/"))
    for child in node.get("children", []):
        if mark_current(child, active):
            is_current = True
    node["current"] = is_current
    return is_current


@cache
def _source_tree(srcdir):
    return collect_folder_tree(srcdir, "")


def add_local_subfolders(app, pagename, templatename, context, doctree):
    folder_tree = copy.deepcopy(_source_tree(str(app.srcdir)))
    if folder_tree:
        mark_current(folder_tree, pagename)
    context["local_subfolders"] = [folder_tree] if folder_tree else []


def setup(app):
    app.connect("html-page-context", add_local_subfolders)
    return {"version": "0.1", "parallel_read_safe": True}
