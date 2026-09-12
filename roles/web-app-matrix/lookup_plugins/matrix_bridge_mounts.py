"""Lookup ``matrix_bridge_mounts``: the secrets that carry each enabled
bridge's config and registration.

Usage (compose templates):

    lookup('compose_volumes', extra_secrets=lookup('matrix_bridge_mounts', 'stack'))
    lookup('container_volumes', 'synapse', extra_secrets=lookup('matrix_bridge_mounts', 'synapse'))
    lookup('container_volumes', service_name, extra_secrets=lookup('matrix_bridge_mounts', 'bridge', item.bridge_name))

Terms:
    stack             -- top-level secret definitions, named by compose_volumes
    synapse           -- one registration mount per bridge
    bridge <name>     -- the config mount of that bridge

Reads from the templating context:
    MATRIX_BRIDGES                    -- enabled bridge configs (set_fact)
    MATRIX_BRIDGE_SOURCE_DIR          -- host directory holding <bridge>/*.yaml
    MATRIX_BRIDGE_CONFIG_TARGET       -- config path inside each bridge
    MATRIX_REGISTRATION_FILE_FOLDER   -- registration folder inside synapse
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

SECRET_MODE = 0o444


def _config_key(bridge: str) -> str:
    return f"mautrix_{bridge}_config"


def _registration_key(bridge: str) -> str:
    return f"mautrix_{bridge}_registration"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        view = str(terms[0]) if terms else ""
        if view not in ("stack", "synapse", "bridge"):
            raise AnsibleError(
                "matrix_bridge_mounts lookup expects 'stack', 'synapse' or "
                f"'bridge <name>', got {terms!r}"
            )

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

        bridges = ctx("MATRIX_BRIDGES")
        if not isinstance(bridges, list):
            raise AnsibleError(
                "matrix_bridge_mounts lookup: MATRIX_BRIDGES must be a list, "
                f"got {type(bridges).__name__}"
            )
        names = [str(bridge["bridge_name"]) for bridge in bridges]

        if view == "bridge":
            if len(terms) != 2 or str(terms[1]) not in names:
                raise AnsibleError(
                    f"matrix_bridge_mounts lookup: 'bridge' needs one enabled bridge name, got {terms[1:]!r}"
                )
            return [
                [
                    {
                        "source": _config_key(str(terms[1])),
                        "target": str(ctx("MATRIX_BRIDGE_CONFIG_TARGET")),
                        "mode": SECRET_MODE,
                    }
                ]
            ]

        if view == "synapse":
            folder = str(ctx("MATRIX_REGISTRATION_FILE_FOLDER"))
            return [
                [
                    {
                        "source": _registration_key(name),
                        "target": f"{folder}mautrix-{name}/registration.yaml",
                        "mode": SECRET_MODE,
                    }
                    for name in names
                ]
            ]

        source_dir = Path(str(ctx("MATRIX_BRIDGE_SOURCE_DIR")))
        secrets: dict[str, dict[str, str]] = {}
        for name in names:
            secrets[_config_key(name)] = {
                "file": str(source_dir / name / "config.yaml")
            }
            secrets[_registration_key(name)] = {
                "file": str(source_dir / name / "registration.yaml")
            }
        return [secrets]
