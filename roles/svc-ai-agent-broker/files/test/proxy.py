"""
Environment:
    ENGINE_SOCKET:  filtered engine socket the socket proxy serves (broker env).
    SELF_NAME:      the broker's own container, used as the exec and delete target.

Prints ``<probe> <status>`` per call, or ``<probe> allowed`` when the proxy
passed the call through. The image cannot be pulled, so a create the proxy
fails to refuse still leaves no container behind.
"""

import os
import re
import sys

sys.path.insert(0, "/opt/broker")

import engine

IMAGE = "agent-broker-proxy-probe:absent"
BIND = [{"Type": "bind", "Source": "/", "Target": "/host"}]
PROBES = {
    "exec": ("POST", "/containers/{self}/exec", {"Cmd": ["true"]}),
    "binds": (
        "POST",
        "/containers/create",
        {"Image": IMAGE, "HostConfig": {"Binds": ["/:/host"]}},
    ),
    "mounts": (
        "POST",
        "/containers/create",
        {"Image": IMAGE, "HostConfig": {"Mounts": BIND}},
    ),
    "service_mounts": (
        "POST",
        "/services/create",
        {
            "Name": "agent-broker-proxy-probe",
            "TaskTemplate": {"ContainerSpec": {"Image": IMAGE, "Mounts": BIND}},
        },
    ),
    "delete": ("DELETE", "/containers/{self}", None),
}

api = engine.Engine(os.environ["ENGINE_SOCKET"], timeout=30)
for name, (method, path, body) in PROBES.items():
    target = path.format(self=os.environ["SELF_NAME"])
    try:
        api.call(method, target, body=body, expect=())
        print(f"{name} allowed", flush=True)
    except engine.EngineError as error:
        status = re.search(r"-> (\d{3})", str(error))
        print(f"{name} {status.group(1) if status else error}"[:200], flush=True)
