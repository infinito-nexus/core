from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.parse

LABEL_PLATFORM = "infinito.agent.platform"
LABEL_OWNER = "infinito.agent.owner"
LABEL_POOL = "infinito.agent.slot"


class EngineError(RuntimeError):
    """Args:
    message: what the call was and how it answered.
    status: HTTP status the engine returned, or None when it never answered.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class Engine:
    """
    Args:
        socket_path: filtered engine socket the socket proxy serves.
        timeout: seconds per API call.
    """

    def __init__(self, socket_path: str, timeout: float):
        self.socket_path = socket_path
        self.timeout = timeout

    def call(
        self, method, path, body=None, query=None, expect=(200, 201, 204), timeout=None
    ):
        target = f"{path}?{urllib.parse.urlencode(query)}" if query else path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        connection = _UnixConnection(self.socket_path, timeout or self.timeout)
        try:
            connection.request(method, target, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
        except OSError as error:
            raise EngineError(f"{method} {path} failed: {error}") from error
        finally:
            connection.close()
        if status not in expect:
            raise EngineError(f"{method} {path} -> {status}: {raw[:400]!r}", status)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode(errors="replace")

    def image_config(self, ref):
        quoted = urllib.parse.quote(ref, safe="")
        try:
            info = self.call("GET", f"/images/{quoted}/json")
        except EngineError:
            name, _, tag = ref.rpartition(":")
            self.call(
                "POST",
                "/images/create",
                query={"fromImage": name, "tag": tag},
                timeout=1800,
            )
            info = self.call("GET", f"/images/{quoted}/json")
        config = info.get("Config") or {}
        return list(config.get("Entrypoint") or []), list(config.get("Cmd") or [])

    def ensure_network(self, name, driver, labels):
        found = self.call(
            "GET",
            "/networks",
            query={"filters": json.dumps({"name": [name]})},
        )
        for network in found or []:
            if network.get("Name") == name:
                return network["Id"]
        created = self.call(
            "POST",
            "/networks/create",
            body={
                "Name": name,
                "Driver": driver,
                "Attachable": driver == "overlay",
                "CheckDuplicate": True,
                "Labels": labels,
            },
        )
        return created["Id"]

    def connect(self, network_id, container, alias, realize_timeout=120, pause=2):
        """Attach ``container`` to ``network_id`` once the network is usable.

        Args:
            network_id: id ``ensure_network`` returned.
            container: container id or name to attach.
            alias: name the other members of the network reach it by.
            realize_timeout: seconds a 404 is tolerated while the engine
                finishes creating the network.
            pause: seconds between attempts.
        """
        deadline = time.monotonic() + realize_timeout
        while True:
            detail = self.call("GET", f"/networks/{network_id}")
            attached = detail.get("Containers") or {}
            if any(key.startswith(container) for key in attached):
                return
            try:
                self.call(
                    "POST",
                    f"/networks/{network_id}/connect",
                    body={
                        "Container": container,
                        "EndpointConfig": {"Aliases": [alias]},
                    },
                    expect=(200, 204),
                )
            except EngineError as error:
                if error.status != 404 or time.monotonic() >= deadline:
                    raise
                time.sleep(pause)
                continue
            return


class ComposeBackend:
    """
    Args:
        engine: the :class:`Engine`.
        runtime: OCI runtime every agent must run under (``runsc``).
    """

    network_driver = "bridge"

    def __init__(self, engine, runtime):
        self.engine = engine
        self.runtime = runtime

    def find(self, name):
        found = self.engine.call(
            "GET",
            "/containers/json",
            query={"all": "true", "filters": json.dumps({"name": [name]})},
        )
        for item in found or []:
            if f"/{name}" in (item.get("Names") or []):
                return self.engine.call("GET", f"/containers/{item['Id']}/json")
        return None

    def list_agents(self):
        found = self.engine.call(
            "GET",
            "/containers/json",
            query={"all": "true", "filters": json.dumps({"label": [LABEL_PLATFORM]})},
        )
        return [
            self.engine.call("GET", f"/containers/{item['Id']}/json")
            for item in found or []
        ]

    @staticmethod
    def env_of(detail):
        return list((detail.get("Config") or {}).get("Env") or [])

    @staticmethod
    def labels_of(detail):
        return dict((detail.get("Config") or {}).get("Labels") or {})

    @staticmethod
    def is_running(detail):
        return bool((detail.get("State") or {}).get("Running"))

    @staticmethod
    def started_at(detail):
        return (detail.get("State") or {}).get("StartedAt") or ""

    def network_for(self, name, labels, container, alias):
        """Return the id of the network this agent and the broker share.

        Args:
            name: agent name, which is also the network name.
            labels: platform and owner labels to put on the network.
            container: the broker's own container, to attach.
            alias: name the agent reaches the broker by.
        """
        network_id = self.engine.ensure_network(name, self.network_driver, labels)
        self.engine.connect(network_id, container, alias)
        return network_id

    def create(self, spec, network_id):
        self.engine.call(
            "POST",
            "/volumes/create",
            body={"Name": spec["volume"], "Labels": spec["labels"]},
        )
        body = {
            "Image": spec["image"],
            "Entrypoint": spec["entrypoint"],
            "Cmd": spec["cmd"],
            "Env": spec["env"],
            "Labels": spec["labels"],
            "HostConfig": {
                "Runtime": self.runtime,
                "Mounts": [
                    {"Type": "volume", "Source": spec["volume"], "Target": spec["data"]}
                ],
                "NanoCpus": spec["nano_cpus"],
                "Memory": spec["memory"],
                "MemoryReservation": spec["memory_reservation"],
                "PidsLimit": spec["pids"],
                "RestartPolicy": {"Name": "unless-stopped"},
                "SecurityOpt": ["no-new-privileges:true"],
                "NetworkMode": spec["network"],
            },
            "NetworkingConfig": {
                "EndpointsConfig": {network_id: {"Aliases": [spec["name"]]}}
            },
        }
        if spec["user"]:
            body["User"] = spec["user"]
        self.engine.call(
            "POST", "/containers/create", body=body, query={"name": spec["name"]}
        )
        return self.find(spec["name"])

    def start(self, detail, network_id=None):
        self.engine.call("POST", f"/containers/{detail['Id']}/start", expect=(204, 304))
        started = self.engine.call("GET", f"/containers/{detail['Id']}/json")
        runtime = (started.get("HostConfig") or {}).get("Runtime")
        if runtime != self.runtime:
            self.engine.call(
                "POST", f"/containers/{detail['Id']}/stop", expect=(204, 304)
            )
            raise EngineError(
                f"{started.get('Name')} came up under '{runtime}', not "
                f"'{self.runtime}'; stopped it rather than run it on the host kernel"
            )
        return started

    def stop(self, detail):
        self.engine.call(
            "POST",
            f"/containers/{detail['Id']}/stop",
            query={"t": "30"},
            expect=(204, 304),
        )
