"""Derive a memory parameter in MiB from the memory limit of a service's container.

    -Xmx{{ lookup('service_memory_mb', application_id, 'search', 0.5) }}m
    memory_limit = {{ lookup('service_memory_mb', application_id, entity_name, 0.5) }}M

The limit is resolved the way ``sys-svc-container`` resolves the container's own
``mem_limit``: ``services.<service>.mem_limit``, then the role's primary entity,
then ``RESOURCE_MEM_LIMIT``. ``share`` is the fraction of that limit the
parameter may claim, so a heap, a cache or a per-request limit follows the
container instead of a literal that drifts away from it.

Sizes are read like Docker reads them: ``k``, ``m`` and ``g`` are binary, a bare
number is bytes. The result is whole MiB, the unit ``-Xmx<n>m``, PHP ``<n>M``,
``memcached -m``, Redis ``<n>mb`` and PostgreSQL ``<n>MB`` all share.
"""

from __future__ import annotations

import re
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.resource_filter import resource_filter

_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([bkmg]?)b?\s*$", re.IGNORECASE)
_FACTOR = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_MEBIBYTE = 1024**2
_HOST_DEFAULT = "RESOURCE_MEM_LIMIT"
_UNDECLARED = object()


def docker_bytes(size: Any) -> int:
    """Return a Docker memory size in bytes.

    Args:
        size: a size such as ``2g``, ``1.5g``, ``512m`` or a byte count.

    Raises:
        AnsibleError: the size is not a number with an optional b/k/m/g unit.
    """
    match = _SIZE.match(str(size))
    if match is None:
        raise AnsibleError(f"lookup('service_memory_mb'): unreadable size {size!r}")
    return int(float(match.group(1)) * _FACTOR[match.group(2).lower()])


def share_mb(mem_limit: Any, share: Any) -> int:
    """Return ``share`` of ``mem_limit`` in whole MiB.

    Args:
        mem_limit: Docker size of the container limit, e.g. ``2g`` or ``512m``.
        share: fraction of the limit, above 0 and at most 1.

    Raises:
        AnsibleError: the share is no fraction in that range, the size is
            unreadable, or the result is below 1 MiB.
    """
    try:
        fraction = float(share)
    except (TypeError, ValueError) as exc:
        raise AnsibleError(
            f"lookup('service_memory_mb'): share {share!r} is not a number"
        ) from exc
    if not 0 < fraction <= 1:
        raise AnsibleError(
            f"lookup('service_memory_mb'): share {share!r} must be above 0 and at most 1"
        )
    megabytes = int(docker_bytes(mem_limit) * fraction) // _MEBIBYTE
    if megabytes < 1:
        raise AnsibleError(
            f"lookup('service_memory_mb'): {share!r} of {mem_limit!r} is below 1 MiB"
        )
    return megabytes


class LookupModule(LookupBase):
    """lookup('service_memory_mb', application_id, service_name, share)"""

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 3:
            raise AnsibleError(
                "lookup('service_memory_mb', application_id, service_name, share) "
                "expects exactly 3 positional terms."
            )
        application_id, service_name, share = terms

        templar = self._templar
        variables = variables or templar.available_variables
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]

        mem_limit = resource_filter(
            applications, application_id, "mem_limit", service_name, _UNDECLARED
        )
        if mem_limit is _UNDECLARED:
            if _HOST_DEFAULT not in variables:
                raise AnsibleError(
                    f"lookup('service_memory_mb'): '{application_id}' declares no "
                    f"mem_limit for '{service_name}' and {_HOST_DEFAULT} is unset"
                )
            mem_limit = templar.template(variables[_HOST_DEFAULT])
        return [share_mb(mem_limit, share)]
