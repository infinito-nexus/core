"""Lookup ``matrix_bridge_mounts``: the synapse registration-file mounts,
one ``<instance>/mautrix/<bridge>:<registration-folder>/mautrix-<bridge>:ro``
short-form entry per enabled bridge.

Usage (compose template):

    extra_volumes=lookup('matrix_bridge_mounts')

Reads from the templating context:
    application_id                    -- the consuming role
    MATRIX_BRIDGES                    -- enabled bridge configs (set_fact)
    MATRIX_REGISTRATION_FILE_FOLDER   -- registration folder inside synapse
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if terms:
            raise AnsibleError("matrix_bridge_mounts lookup expects no terms.")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        def ctx(name: str) -> Any:
            if name not in vars_:
                raise AnsibleError(
                    f"matrix_bridge_mounts lookup: '{name}' is not set in the "
                    "templating context"
                )
            value = vars_[name]
            if templar is not None:
                value = templar.template(value)
            return value

        application_id = str(ctx("application_id")).strip()
        bridges = ctx("MATRIX_BRIDGES")
        reg_folder = str(ctx("MATRIX_REGISTRATION_FILE_FOLDER"))
        if not isinstance(bridges, list):
            raise AnsibleError(
                "matrix_bridge_mounts lookup: MATRIX_BRIDGES must be a list, "
                f"got {type(bridges).__name__}"
            )

        instance_dir = str(
            lookup_loader.get("container", loader=self._loader, templar=templar).run(
                [application_id, "directories.instance"], variables=vars_
            )[0]
        )

        mounts = []
        for bridge in bridges:
            name = str(bridge["bridge_name"])
            mounts.append(f"{instance_dir}mautrix/{name}:{reg_folder}mautrix-{name}:ro")
        return [mounts]
