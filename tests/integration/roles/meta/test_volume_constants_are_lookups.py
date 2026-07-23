"""Every ``*_VOLUME`` constant in a role's vars/main.yml MUST read its
value through one of two accepted forms:

1. Legacy: ``lookup('config', application_id, 'volumes.<key>.<attr>')``
2. New:    ``lookup('volume', application_id, '<key>').<attr>``

A hardcoded volume name (e.g. ``MAILU_ADMIN_DATA_VOLUME: "mailu_admin_data"``)
silently bypasses ``meta/volumes.yml`` and breaks the swarm + NFS rewrite
chain because the central NFS pre-create iterates the meta declarations
only. This test catches the drift before it reaches a deploy.
"""

import re
import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

VOLUME_CONST_LINE_RE = re.compile(
    r"""^(?P<name>[A-Z][A-Z0-9_]*_VOLUME)\s*:\s*(?P<value>.+?)\s*$""",
    re.MULTILINE,
)
LOOKUP_VOLUMES_RE = re.compile(
    r"""lookup\(\s*['"]config['"]\s*,\s*[^,]+,\s*['"]volumes\.[A-Za-z0-9_.\-]+['"]"""
    r"""|"""
    r"""lookup\(\s*['"]volume['"]\s*,\s*[^,]+,\s*['"][A-Za-z0-9_-]+['"]\s*\)\.(?:name|path|type|source|nfs|docker_name|semantic_name)"""
)


def _iter_vars_files():
    for role_dir in sorted(p for p in (PROJECT_ROOT / "roles").iterdir() if p.is_dir()):
        vars_yml = role_dir / ROLE_FILE_VARS_MAIN
        if vars_yml.is_file():
            yield role_dir.name, vars_yml


class TestVolumeConstantsAreLookups(unittest.TestCase):
    def test_every_volume_constant_reads_from_volumes_yml(self):
        offenders: list[str] = []
        for role_name, vars_yml in _iter_vars_files():
            text = read_text(str(vars_yml))
            for match in VOLUME_CONST_LINE_RE.finditer(text):
                name = match.group("name")
                value = match.group("value").strip()
                if not LOOKUP_VOLUMES_RE.search(value):
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{role_name}: vars/main.yml:{line}: '{name}' value "
                        f"does not read from meta/volumes.yml via "
                        f"lookup('config', ..., 'volumes.<key>.<attr>') "
                        f"or lookup('volume', ..., '<key>').<attr>; got: "
                        f"{value}"
                    )
        if offenders:
            self.fail(
                "Volume constants must source their value from "
                "meta/volumes.yml so swarm + NFS rewriting cannot be "
                "bypassed by a hardcoded volume name in vars/main.yml:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
