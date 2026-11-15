from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.docker.image.ref import split_registry_and_name
from utils.env.handlers.infinito.cache.registries import image_registries
from utils.networks.address import subnet_gateway
from utils.templating.vars import resolve_var

if TYPE_CHECKING:
    from collections.abc import Mapping

CACHE_ROLE = "svc-registry-cache"
SUBNET_PATH = "networks.local.subnet"
FRONT_PORT_PATH = "services.front.ports.local.registry"
FLAVOR_PATH = "services.cache.flavor"
FRONTED_FLAVOR = "registry"
MODE_KEYS = ("DEPLOYMENT_MODE", "compose_mode_force")


def unrouted() -> dict[str, Any]:
    """Return the vendor view of a host that routes no image.

    Returns:
        An empty ``front`` and no ``registries``.
    """
    return {"front": "", "registries": []}


def registry_of(reference: str) -> str | None:
    """Return the registry host an image reference pulls from.

    Args:
        reference: ``<name>[:<tag>][@<digest>]``.

    Returns:
        The registry host, or None for a Docker Hub short name or an
        unparsable reference.
    """
    name = reference.strip().split("@", 1)[0]
    if name.rfind(":") > name.rfind("/"):
        name = name.rsplit(":", 1)[0]
    parts = split_registry_and_name(name)
    return parts[0] if parts else None


def cacheable(registry: str) -> bool:
    """Tell whether a registry can sit behind the front as a path component.

    Args:
        registry: a registry host as ``registry_of`` returns it.

    Returns:
        False for ``localhost`` and for a host with a port, whose ``:`` no
        image reference path component may carry.
    """
    return registry != "localhost" and ":" not in registry


def route_reference(reference: str, vendors: Mapping[str, Any] | None) -> str:
    """Prefix a reference with the vendor front when its registry is cached.

    Args:
        reference: the image reference compose or the prepull pulls.
        vendors: what ``lookup('registry_vendors')`` returns for the host.

    Returns:
        ``<front>/<reference>`` when the reference's registry is listed,
        else ``reference`` unchanged.
    """
    front = str((vendors or {}).get("front") or "")
    registries = (vendors or {}).get("registries") or ()
    if front and registry_of(reference) in registries:
        return f"{front}/{reference}"
    return reference


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Return the host's vendor front, or route the given references.

        Args:
            terms: image references to route; none for the vendor view.
            variables: the play variables of the host.
            kwargs: unused.

        Returns:
            One routed reference per term, or ``[{"front": "<gateway>:<port>",
            "registries": [...]}]`` without terms. A host outside the
            ``svc-registry-cache`` group, a swarm deploy, a cache whose
            ``services.cache.flavor`` is not ``registry``, or a repository
            whose role images name no vendor registry routes nothing.
        """
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        vendors = self._vendors(vars_)
        if terms:
            return [route_reference(str(term), vendors) for term in terms]
        return [vendors]

    def _vendors(self, variables: dict[str, Any]) -> dict[str, Any]:
        templar = getattr(self, "_templar", None)
        group_names = resolve_var(templar, variables.get("group_names")) or []
        modes = {
            str(resolve_var(templar, variables.get(key)) or "").strip()
            for key in MODE_KEYS
        }
        if CACHE_ROLE not in group_names or "swarm" in modes:
            return unrouted()
        registries = [r for r in image_registries() if cacheable(r)]
        if not registries:
            return unrouted()
        config = lookup_loader.get("config", loader=self._loader, templar=templar)
        flavor = config.run([CACHE_ROLE, FLAVOR_PATH], variables=variables)[0]
        if str(flavor).strip() != FRONTED_FLAVOR:
            return unrouted()
        subnet = config.run([CACHE_ROLE, SUBNET_PATH], variables=variables)[0]
        port = config.run([CACHE_ROLE, FRONT_PORT_PATH], variables=variables)[0]
        try:
            gateway = subnet_gateway(str(subnet))
        except ValueError as exc:
            raise AnsibleError(f"registry_vendors: {CACHE_ROLE}: {exc}") from exc
        return {"front": f"{gateway}:{port}", "registries": registries}
