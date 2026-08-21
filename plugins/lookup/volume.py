"""Lookup ``volume``: read the canonical ``meta/volumes.yml`` registry.

Two call forms:

  ``lookup('volume', application_id, name)`` — return the normalised dict
  for a single semantic entry. The returned dict always carries:

    - ``name``           the EFFECTIVE docker volume name
                         (entry's ``name:`` if set, otherwise the YAML key)
    - ``semantic_name``  the YAML key from ``meta/volumes.yml``
    - ``docker_name``    the explicit ``name:`` field (alias for ``name``
                         during the dict-of-dicts migration), ``''`` if absent
    - ``path``           the legacy ``path:`` field, ``''`` if absent
    - ``type``           one of ``volume`` | ``bind`` | ``config`` | ``secret``
                         | ``tmpfs``, defaults to ``volume``
    - ``source``         for binds / configs / secrets, ``''`` if absent
    - ``nfs``            NFS opt-in (bool or dict), ``None`` if absent
    - ``mounts``         the raw mounts list, ``[]`` if absent
    - ``targets``        ``{service: container path}`` built from ``mounts``
    - ``target``         the one container path this entry mounts at, present
                         only when every mount agrees. An entry that lands at
                         different paths per service omits the key rather than
                         picking one; read ``targets[service]`` there.

  ``target`` is what lets ``meta/volumes.yml`` stay the single source of a
  container path: a role defines its constant from the registry

      PROMETHEUS_CONFIG_FILE: "{{ lookup('volume', application_id, 'config').target }}"

  rather than repeating the literal, which nothing keeps in step with the
  mount it describes.

  ``lookup('volume', application_id)`` — return the WHOLE canonical
  registry as a dict keyed by semantic name. Useful for tasks that loop
  over every declared volume (e.g. NFS subdir pre-creation). Returns
  ``{}`` for roles with no meta/volumes.yml.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

# nocheck: lookup-cache-import
from utils.cache.applications import get_application_defaults, get_canonical_volumes


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not terms or len(terms) not in (1, 2):
            raise AnsibleError(
                "volume lookup requires 1 (application_id) or 2 "
                "(application_id, name) terms"
            )
        application_id = str(terms[0]).strip()
        if not application_id:
            raise AnsibleError("volume lookup: application_id must be non-empty")

        canonical = get_canonical_volumes(application_id)
        if not canonical:
            get_application_defaults()
            canonical = get_canonical_volumes(application_id)

        if len(terms) == 1:
            return [dict(canonical)]

        name = str(terms[1]).strip()
        if not name:
            raise AnsibleError("volume lookup: name must be non-empty")

        if not canonical:
            raise AnsibleError(
                f"volume lookup: no canonical meta/volumes.yml entries for "
                f"role {application_id!r}"
            )

        entry = canonical.get(name)
        if not isinstance(entry, dict):
            raise AnsibleError(
                f"volume lookup: no entry named {name!r} in canonical "
                f"meta/volumes.yml for role {application_id!r}"
            )

        docker_name = entry.get("name", "")
        mounts = entry.get("mounts", [])
        resolved = {
            "name": entry.get("name") or name,
            "semantic_name": name,
            "docker_name": docker_name,
            "path": entry.get("path", ""),
            "type": entry.get("type", "volume"),
            "source": entry.get("source", ""),
            "nfs": entry.get("nfs", None),
            "mounts": mounts,
            "targets": _targets(mounts),
        }
        distinct = {t for t in resolved["targets"].values() if t}
        if len(distinct) == 1:
            resolved["target"] = next(iter(distinct))
        return [resolved]


def _targets(mounts: Any) -> dict[str, str]:
    """Map each mounting service to the container path it receives.

    Args:
        mounts: the entry's raw ``mounts`` list.
    """
    if not isinstance(mounts, list):
        return {}
    out: dict[str, str] = {}
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        service = str(mount.get("service", "") or "").strip()
        target = str(mount.get("target", "") or "").strip()
        if service and target:
            out[service] = target
    return out
