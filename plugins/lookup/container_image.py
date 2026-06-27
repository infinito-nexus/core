"""Lookup `container_image`: fully-qualified image reference for a
container service, mode-aware.

Single SPOT for assembling the `<registry>/<image>:<version>` reference
that compose/swarm templates feed into `image:` directives.

Returns a full compose ``image:`` line suitable for dropping in as a
standalone template statement:

* Compose mode  - ``image: "<image>:<version>"`` (e.g.
  ``image: "mattermost/mattermost-team-edition:11.8.0"``). No registry
  prefix is applied because compose pulls straight from the upstream
  registry.
* Swarm mode    - the same reference, prefixed with the in-cluster
  registry host:port (e.g.
  ``image: "manager.example.com:5000/mattermost/mattermost-team-edition:11.8.0"``)
  when ``swarm.registry.host`` and ``swarm.registry.port`` are set. With
  no registry configured, swarm falls back to the un-prefixed form.

The wrapping ``image: "<ref>"`` is included in the return value so
templates can call the lookup as a standalone line:

    {{ lookup('container_image', application_id, 'x') }}

instead of repeating ``image:`` and surrounding quotes at every call
site.

Inputs come from the merged application config (``services.<key>.image``
and ``services.<key>.version``). ``image=`` and ``version=`` keyword
overrides bypass those values for ad-hoc references (e.g. side-car
init containers that do not appear in the services map).

When ``custom=True``, the image name is auto-derived from
``application_id`` as ``<entity_name>_custom`` (where ``<entity_name>``
comes from ``utils.roles.entity_name.get_entity_name``). This is the
canonical shape for locally-built images that do not have a registry
upstream. The ``image=`` override still wins over ``custom=True`` when
both are supplied. ``services.<key>.image`` is ignored entirely in
custom mode (the lookup never reads it).

When ``version`` is unset (no services value, no override), the lookup
returns ``image: "<image>"`` (unpinned) and emits a ``display.warning``
so the operator notices the unpinned reference without aborting the
play.

The ``tag_only=True`` kwarg returns the bare ``<image>:<version>``
reference without the ``image: "..."`` wrapping and without the swarm
registry prefix. Use it when the resolved ref must be interpolated
inline (variable assignments, shell snippets, init-container
manifests) rather than dropped as a compose ``image:`` line.

Examples:

    # roles/web-app-X/templates/compose.yml.j2
    {{ lookup('container_image', application_id, 'x') }}

    # Locally-built image (no registry upstream).
    {{ lookup('container_image', application_id, 'x', custom=True) }}

    # Bare reference for inline interpolation.
    X_INIT_IMAGE: "{{ lookup('container_image', application_id, 'x',
                              image='busybox', version='1.36',
                              tag_only=True) }}"

Both terms (application_id, service_key) are required.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.applications import get_merged_applications
from utils.roles.entity_name import get_entity_name

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
        raise AnsibleError(
            f"container_image: unknown application_id '{application_id}'"
        )
    services = app.get("services") or {}
    if not isinstance(services, dict):
        raise AnsibleError(f"container_image: '{application_id}' has no services dict")
    entry = services.get(service_key)
    if not isinstance(entry, dict):
        raise AnsibleError(
            f"container_image: service '{service_key}' missing in "
            f"'{application_id}' services config"
        )
    return entry


def _swarm_prefix(variables: dict[str, Any], templar: Any) -> str:
    raw_mode = variables.get("DEPLOYMENT_MODE", "compose")
    if templar is not None:
        with contextlib.suppress(Exception):
            raw_mode = templar.template(raw_mode)
    deployment_mode = str(raw_mode).strip()
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
                "container_image lookup requires exactly two terms: "
                "application_id and service_key"
            )

        application_id = _as_str(terms[0])
        service_key = _as_str(terms[1])
        if not application_id:
            raise AnsibleError(
                "container_image: application_id must be a non-empty string"
            )
        if not service_key:
            raise AnsibleError(
                "container_image: service_key must be a non-empty string"
            )

        image_override = kwargs.get("image")
        version_override = kwargs.get("version")
        tag_only = bool(kwargs.get("tag_only", False))
        custom = bool(kwargs.get("custom", False))

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=templar,
        )

        entry = _resolve_service_entry(applications, application_id, service_key)

        image_value = _as_str(image_override)
        if not image_value and custom:
            entity_name = _as_str(get_entity_name(application_id))
            if not entity_name:
                raise AnsibleError(
                    f"container_image: cannot derive entity name from "
                    f"application_id '{application_id}' for custom=True"
                )
            image_value = f"{entity_name}_custom"
        if not image_value:
            image_value = _as_str(entry.get("image"))
        if not image_value:
            raise AnsibleError(
                f"container_image: services.{service_key}.image not set for "
                f"'{application_id}' and no image= override provided"
            )

        version_value = _as_str(version_override) or _as_str(entry.get("version"))

        if version_value:
            image_ref = f"{image_value}:{version_value}"
        else:
            _warn(
                f"container_image: services.{service_key}.version not set for "
                f"'{application_id}'; returning unpinned image reference "
                f"'{image_value}'"
            )
            image_ref = image_value

        if tag_only:
            return [image_ref]

        prefix = _swarm_prefix(vars_, templar)
        return [f'image: "{prefix}{image_ref}"']
