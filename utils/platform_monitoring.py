"""The platform monitoring share of a customer instance.

Every name lives in a module of ``utils/monitoring/``; this module re-exports
them and holds the command line the runner calls with ``python3 -I`` before a
release. The ``monitoring``, ``inventory_guard`` and ``release`` scripts load
it by its file path, so it works as ``utils.platform_monitoring`` and alone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if not __package__:
    # nocheck: project-root-import  loaded by file path (python3 -I, spec_from_file_location) outside the utils package, so no package container gives PROJECT_ROOT before utils.monitoring is imported
    _CORE = str(Path(__file__).resolve().parents[1])
    if _CORE not in sys.path:
        sys.path.insert(0, _CORE)

from utils.monitoring.addresses import (
    EMBEDDING_IPV4,
    EXTERNAL_VECTORS,
    GLOBAL_EXCEPTIONS,
    INTERNAL_NETWORKS,
    INTERNAL_VECTORS,
    IPV4_BITS,
    LOOPBACK_NAME,
    LOOPBACK_NAMES,
    federate_sources,
    internal_address,
    platform_address,
    routable,
)
from utils.monitoring.agent import (
    AGENT_BINDING,
    AGENT_COMMAND,
    AGENT_KEY_COMMENT,
    AGENT_KEY_PATTERN,
    AGENT_SECTION,
    HOST_KEY,
    HOST_KEY_VARIABLE,
    KEY_TYPE,
    KEY_TYPES,
    PUBLIC_KEY,
    SITE,
    agent_key_line,
    agent_url,
    host_key_refusals,
)
from utils.monitoring.federation import (
    OPENRESTY_VOLUMES,
    PROMETHEUS_APP,
    configuration_base,
    derived_canonical,
    federation_domain,
)
from utils.monitoring.hosts import (
    CANONICAL_HOSTNAME,
    DOMAIN,
    HOST_LABEL,
    SWARM_MANAGERS,
    canonical_host,
    checkmk_host_name,
    host_segment,
    stack_host,
)
from utils.monitoring.paths import (
    AGENT_KEY_PATH,
    AGENT_KEY_REFERENCE,
    CLAIM_PATH,
    DIGEST_FILE,
    DIGEST_FILE_FIELD,
    DIGEST_FILE_PATH,
    DIGEST_FILES_FIELD,
    DIGEST_MOUNT,
    DIGEST_PATH,
    DIGEST_REFERENCE,
    FEDERATION_MOUNT,
    FEDERATION_PATH,
    MARKER_PATH,
    MONITORED_PATH,
    PATH_SEGMENTS,
    SHA256,
    WORKSPACE_ID,
    agent_key_reference,
    bao_endpoint,
    bao_path,
    digest_entry,
    digest_file_path,
    digest_path,
    digest_reference,
)
from utils.monitoring.share import (
    CHECKMK_APP,
    FEDERATE_MATCHES,
    FEDERATED,
    HEALTH_SERIES,
    KINDS,
    PLATFORM_ONLY,
    ROLE,
    VARIABLE,
    federate_matches,
    inventory_refusals,
    refusals,
    share,
)

__all__ = [
    "AGENT_BINDING",
    "AGENT_COMMAND",
    "AGENT_KEY_COMMENT",
    "AGENT_KEY_PATH",
    "AGENT_KEY_PATTERN",
    "AGENT_KEY_REFERENCE",
    "AGENT_SECTION",
    "CANONICAL_HOSTNAME",
    "CHECKMK_APP",
    "CLAIM_PATH",
    "DIGEST_FILE",
    "DIGEST_FILES_FIELD",
    "DIGEST_FILE_FIELD",
    "DIGEST_FILE_PATH",
    "DIGEST_MOUNT",
    "DIGEST_PATH",
    "DIGEST_REFERENCE",
    "DOMAIN",
    "EMBEDDING_IPV4",
    "EXTERNAL_VECTORS",
    "FEDERATED",
    "FEDERATE_MATCHES",
    "FEDERATION_MOUNT",
    "FEDERATION_PATH",
    "GLOBAL_EXCEPTIONS",
    "HEALTH_SERIES",
    "HOST_KEY",
    "HOST_KEY_VARIABLE",
    "HOST_LABEL",
    "INTERNAL_NETWORKS",
    "INTERNAL_VECTORS",
    "IPV4_BITS",
    "KEY_TYPE",
    "KEY_TYPES",
    "KINDS",
    "LOOPBACK_NAME",
    "LOOPBACK_NAMES",
    "MARKER_PATH",
    "MONITORED_PATH",
    "OPENRESTY_VOLUMES",
    "PATH_SEGMENTS",
    "PLATFORM_ONLY",
    "PROMETHEUS_APP",
    "PUBLIC_KEY",
    "ROLE",
    "SHA256",
    "SITE",
    "SWARM_MANAGERS",
    "VARIABLE",
    "WORKSPACE_ID",
    "agent_key_line",
    "agent_key_reference",
    "agent_url",
    "bao_endpoint",
    "bao_path",
    "canonical_host",
    "checkmk_host_name",
    "configuration_base",
    "derived_canonical",
    "digest_entry",
    "digest_file_path",
    "digest_path",
    "digest_reference",
    "federate_matches",
    "federate_sources",
    "federation_domain",
    "host_key_refusals",
    "host_segment",
    "internal_address",
    "inventory_refusals",
    "main",
    "platform_address",
    "refusals",
    "routable",
    "share",
    "stack_host",
]


def main(argv, stdin, stdout):
    """Args:
        argv: ``digest-file <core>``, ``host-segment <host>`` or
            ``stack-host <host>`` (the inventory of ``ansible-inventory
            --list`` on stdin), as ``host.sh`` runs it on the runner before a
            release.
        stdin: where ``stack-host`` reads.
        stdout: where the answer goes.

    Returns:
        0 with the answer printed, 1 when the stack host is ambiguous or the
        host gives no segment, 2 on an unknown command line.
    """
    if len(argv) == 2 and argv[0] == "digest-file":
        print(digest_path(configuration_base(argv[1])), file=stdout)
        return 0
    if len(argv) == 2 and argv[0] == "host-segment":
        try:
            print(host_segment(argv[1]), file=stdout)
        except ValueError as error:
            print(f"platform_monitoring.py: {error}", file=sys.stderr)
            return 1
        return 0
    if len(argv) == 2 and argv[0] == "stack-host":
        try:
            print(stack_host(json.load(stdin), argv[1]), file=stdout)
        except ValueError as error:
            print(f"platform_monitoring.py: {error}", file=sys.stderr)
            return 1
        return 0
    print(
        "usage: platform_monitoring.py digest-file <core> | host-segment <host>"
        " | stack-host <host>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin, sys.stdout))
