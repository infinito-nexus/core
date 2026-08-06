"""Codec between a role id and the display name CI names carry.

A role id is the machine handle (``web-app-nextcloud``); the display name is
what a human reads off a GitHub Actions job or run title
(``网络应用·Nextcloud``). The category path renders as the ``hanzi`` labels
``meta/categories.yml`` declares, run together into one block, then a ``·``,
then the role's own ``README.md`` heading or the part of the id the categories
do not already carry.

The name never holds a space: the ``whitelist`` and ``priority`` workflow
inputs are space-separated lists, so a display name with a space in it would
make a two-role list unparseable.

:meth:`RoleDisplayName.decode` accepts a raw role id unchanged, so every
consumer can decode unconditionally and a human dispatching a run by hand
never has to type hanzi.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.categories import categories_file

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

SEPARATOR = "·"

_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_VARIANT_SUFFIX = re.compile(r"\s+[\d,]+$")
_ROLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
_VARIATION = re.compile("[︎️]")


class RoleDisplayName:
    """Encode role ids to display names and back, for one repository tree."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = PROJECT_ROOT if root is None else root
        self._tree = load_yaml(str(categories_file(self.root)))["roles"]
        self._by_display: dict[str, str] | None = None

    @property
    def roles_dir(self) -> Path:
        return self.root / "roles"

    def title(self, app_id: str) -> str:
        """The role's ``README.md`` heading as one separator-joined fragment.

        Whitespace inside the heading becomes a ``·`` so a display name never
        holds a space and stays one token in the space-separated ``whitelist``
        and ``priority`` inputs. Variation selectors left behind by an emoji in
        the heading are dropped.

        Args:
            app_id: role id, e.g. ``'web-app-nextcloud'``.
        """
        readme = self.roles_dir / app_id / "README.md"
        heading = _HEADING.search(read_text(str(readme)))
        if not heading:
            raise ValueError(f"{readme} declares no '# ' heading")
        return SEPARATOR.join(_VARIATION.sub("", heading.group(1)).split())

    def id_fragment(self, app_id: str) -> str:
        """The part of the role id the category labels do not already carry.

        A role named after its own category (``update``) leaves no remainder;
        the whole id stands in, so the fragment is never empty.

        Args:
            app_id: role id, e.g. ``'web-app-nextcloud'``.
        """
        parts = app_id.split("-")[len(self.category_labels(app_id)) :]
        return "-".join(parts) or app_id

    def category_labels(self, app_id: str) -> list[str]:
        """The ``hanzi`` label of every category the role id walks through.

        Args:
            app_id: role id, e.g. ``'web-app-nextcloud'``.
        """
        node = self._tree
        labels: list[str] = []
        for part in app_id.split("-"):
            child = node.get(part)
            if not isinstance(child, dict) or "hanzi" not in child:
                break
            labels.append(child["hanzi"])
            node = child
        return labels

    def encode(self, app_id: str, variant: str = "") -> str:
        """The display name for *app_id*, with the variant shard appended.

        The last fragment is the shorter of the heading and the role id's own
        section: a heading that outgrows the id it is meant to read better
        than has lost its point.

        A token with no directory under ``roles/`` encodes to itself: it is a
        sentinel like ``__ALL__``, or a role the tree does not hold, and
        neither has a heading or a category to read.

        Args:
            app_id: role id, e.g. ``'web-app-nextcloud'``.
            variant: variant CSV the job covers, e.g. ``'0,1'`` (``''``: none).
        """
        name = app_id
        if (self.roles_dir / app_id).is_dir():
            fragment = self.id_fragment(app_id)
            title = self.title(app_id)
            if len(title) <= len(fragment):
                fragment = title
            name = SEPARATOR.join(
                part
                for part in ("".join(self.category_labels(app_id)), fragment)
                if part
            )
        return f"{name} {variant}" if variant else name

    def _registry(self) -> dict[str, str]:
        if self._by_display is None:
            self._by_display = {
                self.encode(path.name): path.name
                for path in sorted(self.roles_dir.iterdir())
                if (path / "README.md").is_file()
            }
        return self._by_display

    def decode(self, text: str) -> str | None:
        """The role id *text* names, or None when it names no role.

        Accepts a display name with or without its variant suffix, and a raw
        role id unchanged -- job names from runs that predate the display
        names still parse.

        Args:
            text: a display name or a role id.
        """
        candidate = text.strip()
        for value in (candidate, _VARIANT_SUFFIX.sub("", candidate)):
            if not value:
                continue
            if _ROLE_ID.fullmatch(value) or (self.roles_dir / value).is_dir():
                return value
            if value in self._registry():
                return self._registry()[value]
        return None

    def encode_list(self, app_ids: str) -> str:
        """Space-separated role ids rendered as space-separated display names.

        Args:
            app_ids: space-separated role ids; sentinels like ``__ALL__`` and
                anything that names no role pass through untouched.
        """
        return " ".join(self.encode(token) for token in app_ids.split())

    def decode_list(self, names: str) -> str:
        """Space-separated display names rendered as space-separated role ids.

        Args:
            names: space-separated display names or role ids; anything that
                names no role passes through untouched.
        """
        return " ".join(self.decode(token) or token for token in names.split())


@lru_cache(maxsize=1)
def display_names() -> RoleDisplayName:
    """The codec for the repository the process runs in."""
    return RoleDisplayName()


def main(argv: Sequence[str] | None = None) -> int:
    """Translate one space-separated list between role ids and display names.

    Args:
        argv: ``['<display names>']`` to decode, ``['--encode', '<role ids>']``
            to encode.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    codec = display_names()
    if len(argv) == 2 and argv[0] == "--encode":
        print(codec.encode_list(argv[1]))
        return 0
    if len(argv) != 1:
        raise SystemExit("usage: python -m utils.roles.display [--encode] '<list>'")
    print(codec.decode_list(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
