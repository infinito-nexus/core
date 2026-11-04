"""Lint: every desktop role declares the desktop base as its premise.

Rationale
=========
A ``dsk-*`` role installs something for a person who logs in, so it writes
into that account's home, chowns to its name, or becomes it. The account is
provisioned by ``user-workstation``, which ``dsk-base`` pulls in, and the
service graph is what schedules the two together. A desktop role without the
``desktop-base`` edge is planned into a round where nobody created the
account: ``dsk-gnt-claude`` failed exactly that way with
``chown failed: failed to look up user biber``.

``test_services_declared_load`` catches the other half, a role that reaches
for a provider with ``include_role`` instead of an edge. It cannot catch this
one, because a role that never mentions the provider at all has nothing for
it to look at.

Per-key opt-out
===============
Add ``# nocheck: desktop-base-edge`` to the head of the role's
``meta/services.yml``, naming why the role needs no login account.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "desktop-base-edge"
ROLES_DIR = PROJECT_ROOT / "roles"
PREFIX = "dsk-"
PROVIDER = "dsk-base"
SERVICE_KEY = "desktop-base"


class TestDesktopBaseEdge(unittest.TestCase):
    def test_every_desktop_role_declares_the_base_edge(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(
            p
            for p in ROLES_DIR.iterdir()
            if p.is_dir() and p.name.startswith(PREFIX) and p.name != PROVIDER
        ):
            services_file = role_dir / ROLE_FILE_META_SERVICES
            rel = services_file.relative_to(PROJECT_ROOT).as_posix()
            if not services_file.is_file():
                offenders.append(f"{rel} (missing)")
                continue
            if is_suppressed_in_head(read_text(str(services_file)).splitlines(), _RULE):
                continue
            services = load_yaml_any(str(services_file), default_if_missing={})
            entry = services.get(SERVICE_KEY) if isinstance(services, dict) else None
            if not isinstance(entry, dict):
                offenders.append(f"{rel}: no `{SERVICE_KEY}:` entry")
                continue
            offenders.extend(
                f"{rel}: {SERVICE_KEY}.{flag} is not set"
                for flag in ("enabled", "shared")
                if not entry.get(flag)
            )

        if offenders:
            body = "\n".join(f"  - {o}" for o in offenders)
            self.fail(
                f"\n{len(offenders)} desktop role(s) without the "
                f"`{SERVICE_KEY}` edge:\n{body}\n\n"
                "Fix options:\n"
                f"  (a) Add the edge to the role's {ROLE_FILE_META_SERVICES}:\n"
                "        # nocheck: dynamic-flag  <why the flags stay literal>\n"
                f"        {SERVICE_KEY}:\n"
                "          bond: 1\n"
                "          enabled: true\n"
                "          shared: true\n"
                f"  (b) Add `# nocheck: {_RULE}` to the head of that file, "
                "naming why the role needs no login account."
            )


if __name__ == "__main__":
    unittest.main()
