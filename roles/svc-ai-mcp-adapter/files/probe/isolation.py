"""Prove the adapter sidecar is attached to exactly the networks it may reach.

Runs inside the sidecar itself. A container joined to N docker networks carries
one address per network, so comparing those addresses against the subnets the
deployment declared measures the attachment set by identity rather than by
count, in compose and in swarm alike.

Identity matters once a sidecar legitimately holds more than one attachment: it
reaches its provider over the provider's own subnet and an admitted client over
that pair's subnet, and a count alone cannot tell a second admitted client from
an unrelated network someone else joined it to.

Reachability cannot be used for this. An unknown name does not fail to resolve
here: it falls through to the environment's wildcard resolver, which answers
every name with one address that accepts connections, so a name-based probe
reports every host as reachable regardless of the networks involved.

Environment:
    MCP_EXPECTED_SUBNETS: comma-separated CIDRs the sidecar may be attached to.

Prints the attached addresses and exits non-zero on any address outside the
declared set, or any declared subnet with no address.
"""

import fcntl
import ipaddress
import os
import socket
import struct
import sys

SIOCGIFADDR = 0x8915

expected = [
    ipaddress.ip_network(entry.strip())
    for entry in os.environ.get("MCP_EXPECTED_SUBNETS", "").split(",")
    if entry.strip()
]
if not expected:
    sys.stderr.write(
        "REJECTED MCP_EXPECTED_SUBNETS is empty; nothing to verify against\n"
    )
    sys.exit(1)

probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
attached = []
for _, name in socket.if_nameindex():
    if name == "lo":
        continue
    try:
        packed = fcntl.ioctl(
            probe.fileno(), SIOCGIFADDR, struct.pack("256s", name.encode()[:15])
        )
    except OSError:
        continue
    address = socket.inet_ntoa(packed[20:24])
    attached.append((name, ipaddress.ip_address(address)))
probe.close()

print(" ".join(f"{name}={address}" for name, address in attached))

unexpected = [
    f"{name}={address}"
    for name, address in attached
    if not any(address in subnet for subnet in expected)
]
absent = [
    str(subnet)
    for subnet in expected
    if not any(address in subnet for _, address in attached)
]

if unexpected or absent:
    if unexpected:
        sys.stderr.write(
            f"REJECTED the adapter is attached outside its declared subnets "
            f"({', '.join(unexpected)}); a sidecar holding its provider's credential "
            f"reaches that provider and its admitted clients only\n"
        )
    if absent:
        sys.stderr.write(
            f"REJECTED the adapter is missing a declared attachment "
            f"({', '.join(absent)}); an admitted client cannot reach it\n"
        )
    sys.exit(1)
