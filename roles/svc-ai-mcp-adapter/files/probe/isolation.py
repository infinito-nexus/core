"""Prove the adapter sidecar is attached to exactly one container network.

Runs inside the sidecar itself. A container joined to N docker networks carries
N interfaces besides loopback, so counting them measures the attachment set
directly, in compose and in swarm alike.

Reachability cannot be used for this. An unknown name does not fail to resolve
here: it falls through to the environment's wildcard resolver, which answers
every name with one address that accepts connections, so a name-based probe
reports every host as reachable regardless of the networks involved.

Prints the interface names and exits non-zero when more than one is attached.
"""

import socket
import sys

attached = sorted(name for _, name in socket.if_nameindex() if name != "lo")
print(" ".join(attached))
if len(attached) != 1:
    sys.stderr.write(
        f"REJECTED the adapter is attached to {len(attached)} networks ({', '.join(attached)}); "
        "a sidecar holding its provider's credential must reach that provider only\n"
    )
    sys.exit(1)
