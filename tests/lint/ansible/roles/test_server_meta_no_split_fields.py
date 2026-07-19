"""Self-expiring migration guard: `roles/*/meta/server.yml` MUST NOT carry the
fields that were split into dedicated meta files.

`meta/server.yml`'s `csp`, `domains`, and `networks` blocks were extracted into
`meta/csp.yml`, `meta/domains.yml`, and `meta/networks.yml` (each mapping to
`applications.<app>.<field>`). A branch merged from BEFORE that split would
still ship the combined `server.yml`; the recursive meta-walk would then
silently place those blocks at `applications.<app>.server.{csp,domains,networks}`
-- paths no consumer reads anymore -- so domains / CSP / networks would vanish
at deploy time with NO error. This guard fails loudly on such a merge so the
offending branch gets re-split before it ships.

SELF-EXPIRING: the guard is only useful while pre-split branches may still be
open. From 2026-12-28 it deliberately fails with a reminder to delete it.
"""

from __future__ import annotations

import datetime
import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVER

from . import PROJECT_ROOT

_SPLIT_FIELDS: tuple[str, ...] = ("csp", "domains", "networks")
_SUNSET = datetime.date(2026, 12, 28)


class TestServerMetaNoSplitFields(unittest.TestCase):
    def test_server_yml_has_no_split_fields(self) -> None:
        if datetime.datetime.now(tz=datetime.UTC).date() >= _SUNSET:
            self.fail(
                "Migration guard expired (>= 2026-12-28): the meta/server.yml "
                "-> csp/domains/networks.yml split is long merged. DELETE this "
                "guard test file."
            )

        offenders: list[str] = []
        pattern = f"*/{ROLE_FILE_META_SERVER}"
        for server_yml in sorted((PROJECT_ROOT / "roles").glob(pattern)):
            data = load_yaml_any(str(server_yml), default_if_missing={})
            if not isinstance(data, dict):
                continue
            present = [field for field in _SPLIT_FIELDS if field in data]
            if present:
                rel = server_yml.relative_to(PROJECT_ROOT).as_posix()
                offenders.append(f"{rel}: {present}")

        if offenders:
            self.fail(
                f"{len(offenders)} meta/server.yml still carry split-out "
                "field(s). Move each to its own meta file (csp -> meta/csp.yml, "
                "domains -> meta/domains.yml, networks -> meta/networks.yml; the "
                "file root IS the block's value):\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
