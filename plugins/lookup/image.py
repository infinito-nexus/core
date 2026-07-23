"""Lookup `image`: fully-qualified image reference for a container
service, mode-aware. The SPOT for resolving the
``<registry>/<image>:<version>`` reference.

Returns the bare reference (no ``image:`` wrapping):

* Compose mode  - ``<image>:<version>`` (e.g.
  ``mattermost/mattermost-team-edition:11.8.0``). No registry prefix is
  applied because compose pulls straight from the upstream registry.
* Swarm mode    - the same reference, prefixed with the in-cluster
  registry host:port (e.g.
  ``manager.example.com:5000/mattermost/mattermost-team-edition:11.8.0``)
  when ``swarm.registry.host`` and ``swarm.registry.port`` are set. With
  no registry configured, swarm falls back to the un-prefixed form.

The prefixed form is byte-identical to the container's ``.Config.Image``
after deploy, so it can be matched against a running container exactly.

Inputs come from the merged application config (``services.<key>.image``
and ``services.<key>.version``). ``image=`` and ``version=`` keyword
overrides bypass those values for ad-hoc references (e.g. side-car init
containers that do not appear in the services map).

Locally-built images are declared once, in the service's config:
``services.<key>.custom: true`` names the image ``<entity_name>_custom``
(where ``<entity_name>`` comes from
``utils.roles.entity.name.get_entity_name``) shared across an app's
custom services, while a non-empty STRING names it ``<custom>_custom``
for a second, distinct custom image inside one app (where the shared
``<entity>_custom`` would collide). The compose template's ``build:``
directive does the actual building; this lookup only derives the name
the build is tagged with. A ``custom=`` kwarg overrides the config
declaration, and an ``image=`` override wins over both.
``services.<key>.image`` is ignored entirely in custom mode (the lookup
never reads it).

When ``version`` is unset (no services value, no override), the lookup
returns the bare ``<image>`` (unpinned) and emits a ``display.warning``
so the operator notices the unpinned reference without aborting the play.

The ``tag_only=True`` kwarg returns the reference WITHOUT the swarm
registry prefix. Use it when the ref must be interpolated inline against
the upstream registry rather than the in-cluster mirror.

For the compose ``image: "<ref>"`` line, use the ``container_image``
lookup, which wraps this one.

Both terms (application_id, service_key) are required.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import get_entity_name

try:
    from ansible.utils.display import Display
except Exception:  # pragma: no cover
    Display = None


_display = Display() if Display is not None else None


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _warn(message: str) -> None:
    if _display is not None:
        _display.warning(message)


def _resolve_service_entry(
    applications: dict[str, Any], application_id: str, service_key: str
) -> dict[str, Any]:
    app = applications.get(application_id)
    if not isinstance(app, dict):
        raise AnsibleError(f"image: unknown application_id '{application_id}'")
    services = app.get("services") or {}
    if not isinstance(services, dict):
        raise AnsibleError(f"image: '{application_id}' has no services dict")
    entry = services.get(service_key)
    if not isinstance(entry, dict):
        raise AnsibleError(
            f"image: service '{service_key}' missing in "
            f"'{application_id}' services config"
        )
    return entry


def _swarm_prefix(variables: dict[str, Any], templar: Any) -> str:
    raw_mode = variables.get("DEPLOYMENT_MODE", "compose")
    if templar is not None:
        with contextlib.suppress(Exception):
            raw_mode = templar.template(raw_mode)
    mode_force = variables.get("compose_mode_force", "")
    if templar is not None:
        with contextlib.suppress(Exception):
            mode_force = templar.template(mode_force)
    deployment_mode = str(mode_force or raw_mode).strip()
    if deployment_mode != "swarm":
        return ""

    swarm = variables.get("swarm") or {}
    if templar is not None:
        with contextlib.suppress(Exception):
            swarm = templar.template(swarm)
    if not isinstance(swarm, dict):
        return ""
    registry = swarm.get("registry") or {}
    if not isinstance(registry, dict):
        return ""

    host = _as_str(registry.get("host"))
    port = _as_str(registry.get("port"))
    if not host or not port:
        return ""
    return f"{host}:{port}/"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "image lookup requires exactly two terms: "
                "application_id and service_key"
            )

        application_id = _as_str(terms[0])
        service_key = _as_str(terms[1])
        if not application_id:
            raise AnsibleError("image: application_id must be a non-empty string")
        if not service_key:
            raise AnsibleError("image: service_key must be a non-empty string")

        image_override = kwargs.get("image")
        version_override = kwargs.get("version")
        tag_only = bool(kwargs.get("tag_only", False))
        custom = kwargs.get("custom", False)

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        entry = _resolve_service_entry(applications, application_id, service_key)

        if not custom:
            custom = entry.get("custom") or False

        image_value = _as_str(image_override)
        if not image_value and custom:
            if isinstance(custom, str) and custom.strip():
                custom_base = custom.strip()
            else:
                custom_base = _as_str(get_entity_name(application_id))
            if not custom_base:
                raise AnsibleError(
                    f"image: cannot derive entity name from "
                    f"application_id '{application_id}' for custom=True"
                )
            image_value = f"{custom_base}_custom"
        if not image_value:
            image_value = _as_str(entry.get("image"))
        if not image_value:
            raise AnsibleError(
                f"image: services.{service_key}.image not set for "
                f"'{application_id}' and no image= override provided"
            )

        version_value = _as_str(version_override) or _as_str(entry.get("version"))

        if version_value:
            image_ref = f"{image_value}:{version_value}"
        else:
            _warn(
                f"image: services.{service_key}.version not set for "
                f"'{application_id}'; returning unpinned image reference "
                f"'{image_value}'"
            )
            image_ref = image_value

        if tag_only:
            return [image_ref]

        prefix = _swarm_prefix(vars_, templar)
        return [f"{prefix}{image_ref}"]
