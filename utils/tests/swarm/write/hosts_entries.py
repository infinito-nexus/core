#!/usr/bin/env python3
"""Print ``<ip> <domain>`` lines for every canonical domain
(plus ``www.`` redirects and the primary itself) owned by ``APP_ID``
or its transitive deps.

Inputs (env): ``APP_ID``, ``INFINITO_DOMAIN`` (the SPOT for the
deployment domain; defined in ``default.env`` and exported by
``scripts/meta/env/load.sh``; the development inventory reads the
same env var for the play's ``DOMAIN_PRIMARY``),
``HOSTS_ENTRY_IP`` (optional; address the domains map to,
default ``127.0.0.1``).
"""

from __future__ import annotations

import os
import sys

from plugins.filter.canonical_domains_map import (
    FilterModule as _CanonicalDomainsFilter,
)
from plugins.filter.generate.all_domains import (
    FilterModule as _AllDomainsFilter,
)
from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps

_ROLES_DIR = PROJECT_ROOT / "roles"


def _derived_domains(app_id: str, domain_primary: str) -> list[str]:
    applications = get_merged_applications(roles_dir=str(_ROLES_DIR))
    transitive = applications_if_group_and_all_deps(
        applications,
        [app_id],
        project_root=str(PROJECT_ROOT),
        roles_dir=str(_ROLES_DIR),
    )
    canonical = _CanonicalDomainsFilter().canonical_domains_map(
        applications,
        domain_primary,
        recursive=True,
        roles_base_dir=str(_ROLES_DIR),
        seed=list(transitive),
    )
    derived = _AllDomainsFilter().generate_all_domains(canonical, include_www=True)
    return sorted(
        {
            *derived,
            domain_primary,
            f"www.{domain_primary}",
            f"test.{domain_primary}",
        }
    )


def main() -> int:
    app_id = os.environ["APP_ID"]
    domain_primary = os.environ["INFINITO_DOMAIN"]
    ip = os.environ.get("HOSTS_ENTRY_IP", "127.0.0.1")
    for domain in _derived_domains(app_id, domain_primary):
        print(f"{ip} {domain}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
