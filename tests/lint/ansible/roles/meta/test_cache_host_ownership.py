"""Lint guard for a cached upstream a role reaches but does not declare.

``meta/networks.yml.cache.hosts`` routes an upstream through the package
cache, and exactly one role may own each host: ``utils.cache.hosts._claim``
raises as soon as a second role declares it.

The routing itself is repository-global, not per-deployment:
``utils.cache.hosts.declarations`` walks every directory under ``roles/``, so
the frontend serves a host and the consumers receive its ``extra_hosts`` entry
whenever the cache stack runs, regardless of which roles the round deploys.
This check therefore guards findability, not reachability: the one role
allowed to own a host should be a role that actually fetches from it, so the
declaration is discoverable from the fetch instead of sitting on an unrelated
role that happens to have claimed it first.

Hosts of ``SHARED_OWNER`` are exempt: that role is the cache, so a deployment
that caches at all carries its baseline. Only a role-specific declaration has
to travel with the role that fetches.

``SCANNED_SUFFIXES`` bounds the search to the files that can carry a fetch. A
role's own ``meta/networks.yml`` is read separately, and a README naming an
upstream is prose rather than a fetch.

Fix a violation by moving the declaration to the role that fetches. Where two
roles genuinely share an upstream, only one can own it; mark that entry
``# nocheck: cache-host-ownership`` with the reason and the other roles are
exempt.

The check reads the host as a literal. It therefore sees a URL a role spells
out and misses one a dependency holds: ``argos-net.com``, the case that
prompted this guard, is named nowhere in either libretranslate role because
``argostranslate`` carries it, and a run of this test over the tree that
still had the declaration on the wrong role passes. Closing that gap needs
the upstream of each fetching library, which no file states.

Failure modes covered:
  * A role names a host another role declares under ``cache.hosts`` and
    declares no ``cache.hosts`` entry for it itself.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_NETWORKS

from . import PROJECT_ROOT

_RULE = "cache-host-ownership"
ROLES_DIR = PROJECT_ROOT / "roles"
NETWORKS = ROLE_FILE_META_NETWORKS
SHARED_OWNER = "svc-cache-package"
SCANNED_SUFFIXES = (".yml", ".yaml", ".j2", ".py", ".sh", "Dockerfile")


def _cache_hosts(role_dir) -> dict:
    """Return the ``cache.hosts`` mapping a role declares."""
    try:
        data = load_yaml_any(str(role_dir / NETWORKS), default_if_missing={})
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    cache = data.get("cache")
    hosts = cache.get("hosts") if isinstance(cache, dict) else None
    return hosts if isinstance(hosts, dict) else {}


def _files_by_role() -> dict[str, list[Path]]:
    """Return the files of each role that can carry a fetch, keyed by role."""
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path_str in iter_project_files():
        path = Path(path_str)
        rel = path.relative_to(PROJECT_ROOT).parts
        if len(rel) < 2 or rel[0] != "roles" or path.name == "networks.yml":
            continue
        if path.name.endswith(SCANNED_SUFFIXES):
            grouped[rel[1]].append(path)
    return grouped


class TestCacheHostOwnership(unittest.TestCase):
    def test_a_role_declares_the_cached_hosts_it_reaches(self):
        owners: dict[str, str] = {}
        exempt: set[str] = set()
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            hosts = _cache_hosts(role_dir)
            if not hosts or role_dir.name == SHARED_OWNER:
                continue
            marked = f"# nocheck: {_RULE}" in read_text(str(role_dir / NETWORKS))
            for host in hosts:
                owners[str(host)] = role_dir.name
                if marked:
                    exempt.add(str(host))

        offenders: dict[str, set[str]] = defaultdict(set)
        for role, paths in sorted(_files_by_role().items()):
            declared = set(_cache_hosts(ROLES_DIR / role))
            for path in paths:
                body = read_text(str(path))
                for host, owner in owners.items():
                    if owner == role or host in declared or host in exempt:
                        continue
                    if re.search(rf"\b{re.escape(host)}\b", body):
                        offenders[role].add(
                            f"{host} (declared by {owner}) in "
                            f"{path.relative_to(PROJECT_ROOT)}"
                        )

        if offenders:
            self.fail(
                f"{len(offenders)} role(s) fetch from a cached upstream they do "
                "not declare, so the cache misses whenever the declaring role "
                "is not deployed:\n"
                + "\n".join(
                    f"  - {role}:\n"
                    + "\n".join(f"      * {hit}" for hit in sorted(hits))
                    for role, hits in sorted(offenders.items())
                )
                + f"\n\nFix: move the `cache.hosts` entry to the role that "
                f"fetches, or mark the owning entry `# nocheck: {_RULE}` when "
                "two roles genuinely share it."
            )
