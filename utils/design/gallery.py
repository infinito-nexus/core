from __future__ import annotations

import re
import tempfile
from collections import defaultdict
from pathlib import Path

GALLERY_ROOT = Path(tempfile.gettempdir()) / "design-gallery"
SIDES = ("after", "before")
SHOT_SUFFIX = ".png"
_APP_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

Manifest = dict[str, dict[str, list[str]]]


def app_gallery(root: Path, app: str) -> Path:
    """Return the directory ``make design-gallery`` fills for one app.

    Args:
        root: the gallery root, ``GALLERY_ROOT`` outside tests.
        app: the application id.

    Raises:
        ValueError: ``app`` is no application id.
    """
    if not _APP_ID.fullmatch(app):
        raise ValueError(f"{app!r} is no application id")
    return root / app


def manifest(gallery: Path) -> Manifest:
    """Map every captured side of one app gallery to its views and shots.

    Args:
        gallery: the app's gallery directory.

    Returns:
        ``{side: {view: sorted "<mode>-<viewport>" shots}}`` per side directory
        present; a screenshot is named ``<view>-<mode>-<viewport>.png``, and a
        file without those three parts is left out.
    """
    shots: Manifest = {}
    for side in SIDES:
        folder = gallery / side
        if not folder.is_dir():
            continue
        views: defaultdict[str, list[str]] = defaultdict(list)
        for shot in folder.glob(f"*{SHOT_SUFFIX}"):
            parts = shot.name[: -len(SHOT_SUFFIX)].rsplit("-", 2)
            if len(parts) == 3 and all(parts):
                view, mode, viewport = parts
                views[view].append(f"{mode}-{viewport}")
        shots[side] = {view: sorted(taken) for view, taken in sorted(views.items())}
    return shots


def gaps(shots: Manifest) -> list[str]:
    """List every view that lacks a shot another view of its side has.

    Args:
        shots: a manifest as ``manifest`` returns it.

    Returns:
        ``"<side>/<view>: missing <shot>[, <shot>...]"`` per incomplete view,
        sorted by side and view.
    """
    found: list[str] = []
    for side, views in sorted(shots.items()):
        expected = set().union(*views.values())
        for view, taken in sorted(views.items()):
            missing = sorted(expected.difference(taken))
            if missing:
                found.append(f"{side}/{view}: missing {', '.join(missing)}")
    return found
