from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.mail.provider import MAIL_SERVICE_KEY
from utils.networks.attachments import _is_consumer
from utils.roles.applications.services.registry import discover_role_services
from utils.roles.entity.name import entity_name
from utils.tls.common import get_path

if TYPE_CHECKING:
    from collections.abc import Callable


def smtp_ports(entry: Any, group: str) -> dict[str, int]:
    """
    Args:
        entry: the provider's own ``services.<entity>`` mapping.
        group: ``public`` for the ports it publishes, ``internal`` for the
            ports its container binds.

    Returns:
        The SMTP ports of ``entry.ports.<group>``, keyed by protocol.
    """
    if not isinstance(entry, dict):
        return {}
    ports = (entry.get("ports") or {}).get(group) or {}
    if not isinstance(ports, dict):
        return {}
    out: dict[str, int] = {}
    for name, value in ports.items():
        try:
            out[str(name)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def internal_submission(
    application_id: str,
    provider: str,
    application: Callable[[str], dict[str, Any]],
    ports: Callable[[str], dict[str, int]],
) -> dict[str, Any]:
    """
    Args:
        application_id: the application the lookup resolves for.
        provider: the active mail provider's application id.
        application: returns the applications entry of an application id.
        ports: returns the provider's SMTP ports of a group, as
            ``smtp_ports`` does.

    Returns:
        ``host`` (the provider's service name), ``port``, ``tls``,
        ``start_tls``, ``auth`` and ``auth_mechanism`` of plaintext
        submission with ``AUTH PLAIN``, or ``{}`` when the provider
        publishes its submission port or binds none, *application_id* is a
        mail provider itself, or it does not join the provider's network.
    """
    if ports("public").get("submission"):
        return {}
    port = ports("internal").get("submission")
    if not port:
        return {}
    own = discover_role_services(application_id, application(application_id)).get(
        entity_name(application_id)
    )
    if MAIL_SERVICE_KEY in (own or {}).get("covers", []):
        return {}
    entity = entity_name(provider)
    network = discover_role_services(provider, application(provider)).get(entity)
    if not network or not _is_consumer(
        network,
        application_id,
        lambda app, path, default: get_path(application(app), path, default),
        lambda _app, _key: None,
    ):
        return {}
    return {
        "host": entity,
        "port": port,
        "tls": False,
        "start_tls": False,
        "auth": True,
        "auth_mechanism": "plain",
    }
