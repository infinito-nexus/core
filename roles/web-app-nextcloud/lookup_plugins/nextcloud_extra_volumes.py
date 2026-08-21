"""Lookup ``nextcloud_extra_volumes``: the conditional top-level volume
declarations that must only exist while their feature is on. compose_volumes
declares every ``type: volume`` entry from ``meta/volumes.yml``
unconditionally, so feature-gated volumes are injected here instead of being
listed there - otherwise a disabled whiteboard/recording would still
materialise its volume (and, in swarm, its NFS subdir).

Usage (compose template):

    extra_volumes=lookup('nextcloud_extra_volumes')

Reads from the templating context:
    application_id
    NEXTCLOUD_WHITEBOARD_ENABLED  -- adds whiteboard_tmp + whiteboard_fontcache
    NEXTCLOUD_RECORDING_ENABLED   -- adds talk_recording_tmp

Volume names come from the ``volume`` lookup, so ``meta/volumes.yml`` stays
the single source for naming.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, dict[str, str]]]:
        if terms:
            raise AnsibleError("nextcloud_extra_volumes lookup expects no terms.")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        def ctx(name: str) -> Any:
            if name not in vars_:
                raise AnsibleError(
                    f"nextcloud_extra_volumes lookup: '{name}' is not set in "
                    "the templating context"
                )
            value = vars_[name]
            if templar is not None:
                value = templar.template(value)
            return value

        application_id = str(ctx("application_id")).strip()
        volume_lookup = lookup_loader.get(
            "volume", loader=self._loader, templar=templar
        )

        def volume_name(key: str) -> str:
            return str(
                volume_lookup.run([application_id, key], variables=vars_)[0]["name"]
            )

        extra: dict[str, dict[str, str]] = {}
        if boolean(ctx("NEXTCLOUD_WHITEBOARD_ENABLED")):
            extra["whiteboard_tmp"] = {"name": volume_name("whiteboard_tmp")}
            extra["whiteboard_fontcache"] = {
                "name": volume_name("whiteboard_fontcache")
            }
        if boolean(ctx("NEXTCLOUD_RECORDING_ENABLED")):
            extra["talk_recording_tmp"] = {"name": volume_name("talk_recording_tmp")}
        return [extra]
