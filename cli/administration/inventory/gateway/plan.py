from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.networks.mesh import primary_address
from utils.roles.mapping import ROLE_FILE_META_SERVICES

APPLICATION_ID = "svc-ai-litellm"
SERVICE_KEY = "litellm"
GATEWAY_HOST_KEY = "gateway_host"
ROLE_SERVICES = PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_META_SERVICES


@dataclass(frozen=True)
class Link:
    """One consuming host and the gateway it uses.

    Args:
        consumer: inventory hostname of the consuming host.
        gateway: inventory hostname of the gateway host it names.
        url: the gateway's mesh URL, ``http://<mesh address>:<published port>``.
    """

    consumer: str
    gateway: str
    url: str


def _service(applications: Any) -> Mapping[str, Any]:
    if not isinstance(applications, Mapping):
        return {}
    app = applications.get(APPLICATION_ID) or {}
    services = (app.get("services") or {}) if isinstance(app, Mapping) else {}
    service = (services.get(SERVICE_KEY) or {}) if isinstance(services, Mapping) else {}
    return service if isinstance(service, Mapping) else {}


def gateway_of(applications: Any) -> str:
    """The gateway host a host's ``applications`` names, or ``""``.

    Args:
        applications: the host's ``applications`` block.
    """
    value = _service(applications).get(GATEWAY_HOST_KEY)
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise TypeError(
            f"{APPLICATION_ID}.services.{SERVICE_KEY}.{GATEWAY_HOST_KEY} names a "
            f"host, got {value!r}"
        )
    return value.strip()


def published_port(applications: Any) -> int:
    """The port the gateway host publishes the gateway on.

    Args:
        applications: the gateway host's ``applications`` block; an override
            of ``ports.local.http`` there wins over the role default.
    """
    ports = _service(applications).get("ports") or {}
    override = (ports.get("local") or {}).get("http")
    if override is not None:
        return int(override)
    defaults = load_yaml_any(str(ROLE_SERVICES), default_if_missing={}) or {}
    return int(defaults[SERVICE_KEY]["ports"]["local"]["http"])


def plan_links(hosts: list[str], applications_of: Callable[[str], Any]) -> list[Link]:
    """Every consuming host of the deploy, with the URL its gateway answers on.

    Args:
        hosts: every inventory hostname of the deploy.
        applications_of: hostname to the ``applications`` block of its
            host_vars.

    Raises:
        ValueError: a host names a gateway host no inventory of the deploy
            holds, names itself, names a host that names a gateway of its
            own, or either side holds no mesh address. The message names both
            hosts.
    """
    named = {host: gateway_of(applications_of(host)) for host in hosts}
    links: list[Link] = []
    for consumer in sorted(host for host, gateway in named.items() if gateway):
        gateway = named[consumer]
        if gateway == consumer:
            raise ValueError(f"{consumer} names itself as its gateway host")
        if gateway not in named:
            raise ValueError(
                f"{consumer} names gateway host '{gateway}', which no inventory "
                "of this deploy holds"
            )
        if named[gateway]:
            raise ValueError(
                f"{consumer} names gateway host '{gateway}', which itself names "
                f"'{named[gateway]}': a gateway host runs its own gateway"
            )
        gateway_applications = applications_of(gateway)
        missing = [
            host
            for host, applications in (
                (gateway, gateway_applications),
                (consumer, applications_of(consumer)),
            )
            if not primary_address(applications, host)
        ]
        if missing:
            raise ValueError(
                f"{consumer} uses the gateway on {gateway}, but "
                f"{' and '.join(missing)} hold(s) no mesh address: run "
                "cli.administration.inventory.mesh over every inventory first"
            )
        address = primary_address(gateway_applications, gateway)
        links.append(
            Link(
                consumer=consumer,
                gateway=gateway,
                url=f"http://{address}:{published_port(gateway_applications)}",
            )
        )
    return links
