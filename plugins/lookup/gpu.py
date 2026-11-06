"""Whether a service gets a GPU: it asked for one AND the host carries one.

Two facts have to agree and used to be restated at every call site. The
declaration lives in ``applications`` under ``services.<service>.gpu``; the
hardware is ``sys-svc-container``'s two stats on the target host: the device
node ``/dev/nvidia0`` (``sys_svc_container_nvidia_device``) and the driver's
``nvidia-smi`` (``sys_svc_container_nvidia_driver``). Asking only the
declaration selects a ``-cuda`` image on a host that has no device, and that
tag has no arm64 manifest at all, so the build fails with ``no match for
platform in manifest``. A privileged container sees the host's device node
without the driver, so the node alone does not make a GPU host either.

The stats are target-host facts, so this reads the registers out of the
play's variables rather than inspecting the controller it runs on.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.resource_filter import resource_filter

DEVICE_FACT = "sys_svc_container_nvidia_device"
DRIVER_FACT = "sys_svc_container_nvidia_driver"


def _stat_exists(variables: dict, fact: str) -> bool:
    """Whether a stat register of the target host found its path.

    Args:
        variables: the play's variables, carrying the register.
        fact: name of the register.

    Returns:
        False while the register is absent, which is also the answer before
        ``sys-svc-container`` has run.
    """
    register = variables.get(fact) or {}
    if not isinstance(register, dict):
        return False
    return bool((register.get("stat") or {}).get("exists"))


def _device_present(variables: dict) -> bool:
    """Whether the target host carries an NVIDIA device node and its driver.

    Args:
        variables: the play's variables, carrying both registers.

    Returns:
        True only when both stats found their path.
    """
    return _stat_exists(variables, DEVICE_FACT) and _stat_exists(variables, DRIVER_FACT)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict | None = None,
        **kwargs: Any,
    ) -> list[bool]:
        """Return ``[bool]``: the service is GPU-accelerated on this host.

        Args:
            terms: ``application_id`` and optionally the service name; the
                service defaults to the application's own entity.
            variables: the play's variables.

        Raises:
            AnsibleError: wrong number of terms.
        """
        if not 1 <= len(terms) <= 2:
            raise AnsibleError(
                "gpu: expected 1 or 2 terms: lookup('gpu', application_id[, service])"
            )
        application_id = str(terms[0])
        service_name = str(terms[1]) if len(terms) == 2 else ""

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]

        wanted = resource_filter(
            applications, application_id, "gpu", service_name, False
        )
        return [boolean(wanted, strict=False) and _device_present(variables)]
