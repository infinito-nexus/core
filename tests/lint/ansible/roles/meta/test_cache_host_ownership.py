"""Lint guard for a cached upstream a role reaches but does not declare.

``meta/networks.yml.cache.hosts`` routes an upstream through the package
cache, and exactly one role may own each host: ``utils.cache.hosts.claim``
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

Hosts declared ``hijack: "false"`` are exempt too: they get no listener and no
``extra_hosts`` entry, so a role naming one reaches the upstream itself, and
only the artefact its owner pins under the base route flows through the cache.

``SCANNED_SUFFIXES`` bounds the search to the files that can carry a fetch. A
role's own ``meta/networks.yml`` is read separately, and a README naming an
upstream is prose rather than a fetch. ``meta/info.yml`` is skipped for that
second reason: its ``homepage`` is where a human reads about the application,
so a role whose upstream publishes on a cached domain would otherwise be
charged with fetching from it. ``meta/license.yml`` is skipped for the same
reason: its ``url`` cites where the licence was read, and nothing fetches it.

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
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files, read_text
from utils.cache.hosts import declarations
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_LICENSE,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_TASKS_MAIN,
)

from . import PROJECT_ROOT

_RULE = "cache-host-ownership"
ROLES_DIR = PROJECT_ROOT / "roles"
NETWORKS = ROLE_FILE_META_NETWORKS
SHARED_OWNER = "svc-cache-package"
SCANNED_SUFFIXES = (".yml", ".yaml", ".j2", ".py", ".sh", "Dockerfile")
UNFETCHED = (
    Path(NETWORKS).name,
    Path(ROLE_FILE_META_INFO).name,
    Path(ROLE_FILE_META_LICENSE).name,
)


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
        if len(rel) < 2 or rel[0] != "roles" or path.name in UNFETCHED:
            continue
        if path.name.endswith(SCANNED_SUFFIXES):
            grouped[rel[1]].append(path)
    return grouped


def _owners(roles_dir: Path, unhijacked: set[str]) -> tuple[dict[str, str], set[str]]:
    """Return the owning role of each judged host, and the hosts marked shared.

    Args:
        roles_dir: the ``roles`` directory whose ``meta/networks.yml`` files declare the hosts.
        unhijacked: the hosts declared ``hijack: "false"``. Such a host gets no
            listener and no ``extra_hosts`` entry, so a role naming it reaches the
            upstream itself; only an artefact pinned under its base route touches
            the cache, and no other role misses the cache for want of it.
    """
    owners: dict[str, str] = {}
    exempt: set[str] = set()
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        hosts = _cache_hosts(role_dir)
        if not hosts or role_dir.name == SHARED_OWNER:
            continue
        marked = f"# nocheck: {_RULE}" in read_text(str(role_dir / NETWORKS))
        for host in (str(name) for name in hosts if str(name) not in unhijacked):
            owners[host] = role_dir.name
            if marked:
                exempt.add(host)
    return owners, exempt


def _offenders(
    roles_dir: Path, files: dict[str, list[Path]], unhijacked: set[str]
) -> dict[str, set[str]]:
    """Return, per role, the judged hosts it names but neither owns nor declares.

    Args:
        roles_dir: the ``roles`` directory, beside the files' project root.
        files: the files of each role that can carry a fetch, keyed by role.
        unhijacked: the hosts declared ``hijack: "false"``, which are not judged.
    """
    owners, exempt = _owners(roles_dir, unhijacked)
    offenders: dict[str, set[str]] = defaultdict(set)
    for role, paths in sorted(files.items()):
        declared = set(_cache_hosts(roles_dir / role))
        judged = {
            host: owner
            for host, owner in owners.items()
            if owner != role and host not in declared and host not in exempt
        }
        for path in paths:
            body = read_text(str(path))
            offenders[role].update(
                f"{host} (declared by {owner}) in {path.relative_to(roles_dir.parent)}"
                for host, owner in judged.items()
                if re.search(rf"\b{re.escape(host)}\b", body)
            )
    return {role: hits for role, hits in offenders.items() if hits}


class TestCacheHostOwnership(unittest.TestCase):
    def test_a_role_declares_the_cached_hosts_it_reaches(self):
        unhijacked = {entry.host for entry in declarations().hosts if not entry.hijack}
        offenders = _offenders(ROLES_DIR, _files_by_role(), unhijacked)
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

    def test_only_a_hijacked_host_binds_a_foreign_role_that_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            networks = roles_dir / "svc-owner" / NETWORKS
            networks.parent.mkdir(parents=True)
            networks.write_text(
                "cache:\n"
                "  hosts:\n"
                "    hijacked.example:\n"
                "      repo: raw-x\n"
                "    broad.example:\n"
                "      repo: raw-x\n"
                '      hijack: "false"\n',
                encoding="utf-8",
            )
            fetch = roles_dir / "web-app-user" / ROLE_FILE_TASKS_MAIN
            fetch.parent.mkdir(parents=True)
            fetch.write_text(
                "- get_url:\n"
                "    url: https://hijacked.example/a\n"
                "- get_url:\n"
                "    url: https://broad.example/b\n",
                encoding="utf-8",
            )
            files = {"web-app-user": [fetch]}
            spared = _offenders(roles_dir, files, {"broad.example"})
            unspared = _offenders(roles_dir, files, set())
        where = f"in roles/web-app-user/{ROLE_FILE_TASKS_MAIN}"
        self.assertEqual(
            {"web-app-user": {f"hijacked.example (declared by svc-owner) {where}"}},
            spared,
        )
        self.assertEqual(
            {
                f"hijacked.example (declared by svc-owner) {where}",
                f"broad.example (declared by svc-owner) {where}",
            },
            unspared["web-app-user"],
        )
