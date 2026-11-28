"""Forbid direct ``container`` uses of ``lookup('database')`` and of
``lookup('engine')`` for an HA-capable engine.

In HA form a central engine has no single container, so both lookups raise
on ``container``. A caller of an HA-capable engine that treats ``container``
as a plain name (a ``--filter name=``, a network disconnect, a compose cid)
therefore breaks only once the engine gains hosts. Use ``address`` inside a
shell command, or ``swarm/resolve/primary.yml`` for node + container id.
Engines that never render an HA form keep ``container``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content
from utils.roles.applications.services.engines import ENGINES
from utils.roles.db.instances import ha_spec

from . import PROJECT_ROOT

_DIRECT_CONTAINER = re.compile(
    r"lookup\(\s*['\"](?P<kind>database|engine)['\"]"
    r"(?:\s*,\s*['\"](?P<engine>[a-z]+)['\"])?[^)]*,\s*['\"]container['\"]\s*\)"
)


def _ha_capable_engine(engine: str | None) -> bool:
    descriptor = ENGINES.get(engine or "")
    return bool(descriptor) and ha_spec(descriptor["svc"])["capable"]


def _direct_uses() -> dict[str, int]:
    found: dict[str, int] = {}
    for path_str, content in iter_project_files_with_content(
        extensions=(".yml", ".yaml", ".j2"),
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith("roles/"):
            continue
        hits = sum(
            1
            for match in _DIRECT_CONTAINER.finditer(content)
            if match.group("kind") == "database"
            or _ha_capable_engine(match.group("engine"))
        )
        if hits:
            found[rel] = hits
    return found


class TestNoDirectDbContainer(unittest.TestCase):
    def test_engine_scope_follows_ha_capable(self) -> None:
        self.assertTrue(_ha_capable_engine("redis"))
        self.assertFalse(_ha_capable_engine("memcached"))

    def test_no_direct_container_uses(self) -> None:
        found = _direct_uses()
        if found:
            self.fail(
                "Direct lookup('database'|'engine', ..., 'container') uses of an "
                "HA-capable engine. In HA form 'container' is unavailable. Use "
                "'address' inside a shell command or "
                "roles/sys-svc-compose/tasks/utils/swarm/resolve/primary.yml.\n"
                + "\n".join(f"- {p}: {c}" for p, c in sorted(found.items()))
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
