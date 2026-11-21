from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache.base import _render_with_templar
from utils.roles.entity.name import entity_name


class ModeSwitchLookup(LookupBase):
    """lookup('<SWITCH>'[, role])

    Args:
        role: the role whose switch is read; the calling task's
            ``application_id`` when omitted.

    Returns:
        ``services.<entity>.<SWITCH>.enabled`` of the role's primary entity as
        a bool when the role's ``meta/services.yml`` or the inventory at
        ``applications.<role>`` sets it, otherwise the global ``<GLOBAL>``.
    """

    SWITCH: ClassVar[str] = "debug"
    GLOBAL: ClassVar[str] = "DEBUG"

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if terms and len(terms) > 1:
            raise AnsibleError(
                f"{self._name()} takes at most one term: the role (defaults to "
                "application_id)."
            )
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        role = self._role(terms, variables, templar)
        path = f"services.{entity_name(role)}.{self.SWITCH}"
        config = lookup_loader.get(
            "config", loader=getattr(self, "_loader", None), templar=templar
        )
        switch = config.run(
            [role, path, {}], variables=variables, roles_dir=kwargs.get("roles_dir")
        )[0]
        if not isinstance(switch, Mapping):
            raise AnsibleError(
                f"{self._name()}: {path} of {role} must be a mapping holding `enabled`."
            )
        if "enabled" in switch:
            return [self._bool(switch["enabled"], f"{path}.enabled of {role}")]
        if self.GLOBAL not in variables:
            raise AnsibleError(f"{self._name()}: {self.GLOBAL} is not defined.")
        value = _render_with_templar(
            variables[self.GLOBAL], templar=templar, variables=variables
        )
        return [self._bool(value, self.GLOBAL)]

    def _name(self) -> str:
        return f"lookup('{self.SWITCH}')"

    def _role(self, terms, variables: dict[str, Any], templar: Any) -> str:
        if terms:
            role = str(terms[0]).strip()
        elif "application_id" in variables:
            role = str(
                _render_with_templar(
                    variables["application_id"], templar=templar, variables=variables
                )
            ).strip()
        else:
            raise AnsibleError(
                f"{self._name()}: pass the role as term, the calling task defines "
                "no application_id."
            )
        if not role:
            raise AnsibleError(f"{self._name()}: the role is empty.")
        return role

    def _bool(self, value: Any, source: str) -> bool:
        try:
            return boolean(value, strict=True)
        except TypeError as error:
            raise AnsibleError(
                f"{self._name()}: {source} is {value!r}, not a boolean."
            ) from error


class LookupModule(ModeSwitchLookup):
    SWITCH = "debug"
    GLOBAL = "DEBUG"
