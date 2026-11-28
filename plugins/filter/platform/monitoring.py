from __future__ import annotations

import os

from ansible.errors import AnsibleFilterError

from utils.openbao_client import OpenBaoError, resolve
from utils.platform_monitoring import (
    ROLE,
    agent_key_line,
    agent_key_reference,
    agent_url,
    digest_entry,
    digest_path,
    digest_reference,
    federate_matches,
    federate_sources,
    host_segment,
    share,
)


def platform_monitoring_share(value):
    """Args:
        value: the host's ``platform_monitoring``, None when the inventory
            sets none.

    Returns:
        Every share kind mapped to whether the host shares it.

    Raises:
        AnsibleFilterError: the value breaks the share schema.
    """
    try:
        return share(value)
    except ValueError as exc:
        raise AnsibleFilterError(f"platform_monitoring_share: {exc}") from exc


def platform_monitoring_federate(shared):
    """Args:
        shared: the result of ``platform_monitoring_share``.

    Returns:
        The ``match[]`` selectors the instance's ``/federate`` answers.
    """
    return federate_matches(shared)


def platform_monitoring_agent_key_line(public_key, address, workspace):
    """Args:
        public_key: the platform monitoring public key.
        address: the Checkmk host's address.
        workspace: the bare workspace id the deploy runs for.

    Returns:
        The restricted, workspace-bound ``authorized_keys`` line of
        ``agent_key_line``.

    Raises:
        AnsibleFilterError: the key, the address or the workspace is refused.
    """
    try:
        return agent_key_line(public_key, address, workspace)
    except ValueError as exc:
        raise AnsibleFilterError(f"platform_monitoring_agent_key_line: {exc}") from exc


def platform_monitoring_digest_entry(digest, host):
    """Args:
        digest: the SHA-256 hex digest of the host's federation token.
        host: ``inventory_hostname``.

    Returns:
        The digest file line of ``digest_entry``.

    Raises:
        AnsibleFilterError: the digest is malformed or the host gives no
            segment.
    """
    try:
        return digest_entry(digest, host)
    except ValueError as exc:
        raise AnsibleFilterError(f"platform_monitoring_digest_entry: {exc}") from exc


def platform_monitoring_host_segment(host):
    """Args:
        host: ``inventory_hostname``.

    Returns:
        The ``host_segment`` its digest line starts with.

    Raises:
        AnsibleFilterError: the host gives no segment.
    """
    try:
        return host_segment(host)
    except ValueError as exc:
        raise AnsibleFilterError(f"platform_monitoring_host_segment: {exc}") from exc


def platform_monitoring_agent_url(server, site, sha256):
    """Args:
        server: the Checkmk domain the platform injects.
        site: its Checkmk site.
        sha256: the digest of the agent script the site serves.

    Returns:
        The agent script URL of ``agent_url``.

    Raises:
        AnsibleFilterError: a platform value is empty or malformed.
    """
    try:
        return agent_url(server, site, sha256)
    except ValueError as exc:
        raise AnsibleFilterError(f"platform_monitoring_agent_url: {exc}") from exc


def platform_monitoring_federate_sources(workspace, address):
    """Args:
        workspace: ``WORKSPACE`` of the deploy.
        address: ``PLATFORM_PROMETHEUS_ADDRESS`` the platform injects.

    Returns:
        The source addresses of ``federate_sources``.

    Raises:
        AnsibleFilterError: inside a workspace, the address is refused.
    """
    try:
        return federate_sources(workspace, address)
    except ValueError as exc:
        raise AnsibleFilterError(
            f"platform_monitoring_federate_sources: {exc}"
        ) from exc


def platform_monitoring_resolve(reference, credential):
    """Args:
        reference: the OpenBao reference core derives from ``WORKSPACE`` and
            the host, never one the inventory holds.
        credential: the credential name the failures name.

    Returns:
        The field the reference names, read through the deploy's own OpenBao
        session as ``lookup('config')`` reads inventory references.

    Raises:
        AnsibleFilterError: OpenBao refuses or lacks the field.
    """
    try:
        return resolve(reference, f"secrets.credentials.{credential}", ROLE, os.environ)
    except OpenBaoError as exc:
        raise AnsibleFilterError(f"platform_monitoring_resolve: {exc}") from exc


class FilterModule:
    def filters(self):
        return {
            "platform_monitoring_share": platform_monitoring_share,
            "platform_monitoring_federate": platform_monitoring_federate,
            "platform_monitoring_digest": digest_path,
            "platform_monitoring_digest_entry": platform_monitoring_digest_entry,
            "platform_monitoring_host_segment": platform_monitoring_host_segment,
            "platform_monitoring_digest_reference": digest_reference,
            "platform_monitoring_agent_key_reference": agent_key_reference,
            "platform_monitoring_agent_key_line": platform_monitoring_agent_key_line,
            "platform_monitoring_agent_url": platform_monitoring_agent_url,
            "platform_monitoring_federate_sources": platform_monitoring_federate_sources,
            "platform_monitoring_resolve": platform_monitoring_resolve,
        }
