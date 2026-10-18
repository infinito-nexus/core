"""Lint: a role stylesheet only reads design custom properties that reach it.

``sys-front-inj-design`` builds the per-app stylesheet by rendering
``templates/css/app.css.j2`` - a ``:root{}`` block of ``--design-url-*``,
``--design-slot-*`` and ``--design-url-app-*`` declarations - and appending the
role's sheet and, when the role ships a logo, its ``files/logo.css``. The sheet
is whichever of ``templates/style.css.j2`` and ``files/style.css`` the
``first_found`` in that role's ``tasks/main.yml`` resolves, in that order.
Those three files are the only ones that block reaches.

A sheet the role deploys on its own path never sees it. Reading a design
custom property there is invisible: an undefined custom property makes the
whole declaration invalid at computed-value time, so the rule silently paints
nothing and no test, no lint and no colour-asserting Playwright spec notices.
That is how a FusionDirectory tree-list lost its guide lines.

The same silence hides a typo. ``var(--design-url-sidbar-svg)`` is a valid
stylesheet; it just never matches. So every referenced slot is checked against
the slots the role actually declares - its own ``meta/services.yml``
``design.slots`` merged over the global set in ``web-svc-design`` - and every
``--design-url-app-<key>`` against the ``design_css_urls`` of its role.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path

ROLES = PROJECT_ROOT / "roles"
GLOBAL_SLOTS_ROLE = "web-svc-design"
COMPOSED = ("templates/style.css.j2", "files/style.css", "files/logo.css")
KINDS = ("png", "svg")
DIMENSIONS = ("width", "height")
FAVICON = "favicon-ico"
REFERENCE = re.compile(r"var\(\s*--design-(url|slot)-([A-Za-z0-9_-]+)\s*[,)]")
RULE = "design-custom-properties"


def _design(role: str) -> dict:
    """Return the ``design`` service entry of one role.

    :param role: role directory name.
    :return: the mapping, empty when the role declares none.
    """
    path = ROLES / role / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return {}
    parsed = load_yaml_str(read_text(str(path))) or {}
    entry = parsed.get("design")
    return entry if isinstance(entry, dict) else {}


def _slots(role: str) -> set[str]:
    """Return every design slot the role resolves, global ones included."""
    names = set(_design(GLOBAL_SLOTS_ROLE).get("slots") or {})
    return names | set(_design(role).get("slots") or {})


def _app_urls(role: str) -> set[str]:
    """Return the keys of the role's ``design_css_urls``."""
    path = ROLES / role / ROLE_FILE_VARS_MAIN
    if not path.is_file():
        return set()
    try:
        parsed = load_yaml_str(read_text(str(path))) or {}
    except Exception:
        return set()
    entry = parsed.get("design_css_urls")
    return set(entry) if isinstance(entry, dict) else set()


def _emitted(role: str) -> set[str]:
    """Return every custom property ``app.css.j2`` declares for this role."""
    names = {f"url-{FAVICON}"}
    for slot in _slots(role):
        names.update(f"url-{slot}-{kind}" for kind in KINDS)
        names.update(f"slot-{slot}-{dimension}" for dimension in DIMENSIONS)
    names.update(f"url-app-{key}" for key in _app_urls(role))
    return names


def _referenced(path: Path) -> set[str]:
    return {f"{kind}-{name}" for kind, name in REFERENCE.findall(read_text(str(path)))}


class TestDesignCustomProperties(unittest.TestCase):
    def test_only_composed_sheets_read_design_properties(self) -> None:
        candidates = sorted(ROLES.glob("*/**/*.css*"))
        self.assertTrue(candidates, f"[{RULE}] no role stylesheet found under {ROLES}")
        offenders = [
            str(path.relative_to(PROJECT_ROOT))
            for path in candidates
            if _referenced(path)
            and "/".join(path.relative_to(ROLES).parts[1:]) not in COMPOSED
        ]
        self.assertFalse(
            offenders,
            f"[{RULE}] these read a design custom property, but "
            "sys-front-inj-design prepends the declarations only to "
            f"{', '.join(COMPOSED)}, so the value never arrives and the "
            "declaration is dropped:\n  " + "\n  ".join(offenders),
        )

    def test_every_referenced_property_is_declared(self) -> None:
        sheets = [path for name in COMPOSED for path in sorted(ROLES.glob(f"*/{name}"))]
        self.assertTrue(sheets, f"[{RULE}] no composed sheet found under {ROLES}")
        offenders = []
        for path in sheets:
            role = path.relative_to(ROLES).parts[0]
            missing = sorted(_referenced(path) - _emitted(role))
            if missing:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {missing}")
        self.assertFalse(
            offenders,
            f"[{RULE}] these read custom properties that app.css.j2 never "
            "declares for their role. Add the slot to the role's "
            "meta/services.yml design.slots, or the key to its "
            "design_css_urls:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
