"""The swarm backend: agents as single-replica services on a pool of overlays."""

from __future__ import annotations

import json
import threading

from engine import LABEL_PLATFORM, LABEL_POOL, EngineError


class SwarmBackend:
    """
    Args:
        engine: the :class:`engine.Engine`.
        constraint: placement constraint of the sandbox nodes.
        network_prefix: name every pool network starts with.
        slots: how many pool networks there are, one per concurrent agent.
    """

    network_driver = "overlay"

    def __init__(self, engine, constraint, network_prefix, slots):
        self.engine = engine
        self.constraint = constraint
        self.network_prefix = network_prefix
        self.slots = slots
        self._pool = []
        self._reserved = {}
        self._claim = threading.Lock()

    def ensure_pool(self, container, alias):
        """Create the pool networks and put the broker's own service on them.

        Exception: a service task cannot be attached to a network at runtime,
        and an overlay is realized per node, so the broker cannot reach a
        network an agent created on a sandbox node. The networks therefore
        exist up front and enter the broker's own service spec, which costs one
        reschedule of this task the first time and none afterwards.

        Args:
            container: the broker's own container, whose service spec is updated.
            alias: name the agents reach the broker by.
        """
        self._pool = [
            self.engine.ensure_network(
                f"{self.network_prefix}-{slot}",
                self.network_driver,
                {LABEL_POOL: str(slot)},
            )
            for slot in range(self.slots)
        ]
        detail = self.engine.call("GET", f"/containers/{container}/json")
        service_id = ((detail.get("Config") or {}).get("Labels") or {}).get(
            "com.docker.swarm.service.id"
        )
        if not service_id:
            raise EngineError(f"{container} carries no swarm service id")
        current = self.engine.call("GET", f"/services/{service_id}")
        spec = current["Spec"]
        replicas = ((spec.get("Mode") or {}).get("Replicated") or {}).get("Replicas")
        if (replicas or 1) > 1:
            raise EngineError(
                f"the broker is scaled to {replicas} replicas; it claims agent "
                "networks and remembers agent keys in one process, so a second "
                "replica would hand one network to two owners"
            )
        attached = spec["TaskTemplate"].get("Networks") or []
        missing = [
            network_id
            for network_id in self._pool
            if network_id not in {entry.get("Target") for entry in attached}
        ]
        if not missing:
            return
        spec["TaskTemplate"]["Networks"] = attached + [
            {"Target": network_id, "Aliases": [alias]} for network_id in missing
        ]
        self.engine.call(
            "POST",
            f"/services/{service_id}/update",
            body=spec,
            query={"version": current["Version"]["Index"]},
        )

    def _occupancy(self, name):
        """Return this agent's own pool network and the ones others hold.

        Exception: a service counts as holding its networks from the moment
        its desired replica count is raised, not from the moment a task
        reports running. The engine records the desired count synchronously,
        so a claim is visible to the next caller immediately; waiting for the
        task would leave a window in which the same network is handed out
        twice and two agents share one network.

        Args:
            name: agent name to report separately from the others.
        """
        held, taken = None, set()
        for detail in self.list_agents():
            spec = detail.get("Spec") or {}
            mode = (spec.get("Mode") or {}).get("Replicated") or {}
            if (mode.get("Replicas") or 0) < 1:
                continue
            targets = {
                entry.get("Target")
                for entry in (spec.get("TaskTemplate") or {}).get("Networks") or []
            }
            if spec.get("Name") == name:
                held = next((one for one in self._pool if one in targets), None)
            else:
                taken |= targets
        taken |= {
            network for holder, network in self._reserved.items() if holder != name
        }
        return held or self._reserved.get(name), taken

    def network_for(self, name, labels, container, alias):
        """Return the pool network this agent gets to itself.

        A pool network holds the broker and at most one agent, so an agent
        still reaches nothing but the broker. A stopped agent releases its
        network. The claim is taken under a lock and remembered until the
        agent stops, because two owners starting their first agent at once
        would otherwise be handed the same free network.

        Args:
            name: agent name, whose own network is kept when it has one.
            labels: unused; a pool network is labelled by slot, not by owner.
            container: unused; the broker joins the pool through its service spec.
            alias: unused; the alias is set when the pool is built.
        """
        with self._claim:
            held, taken = self._occupancy(name)
            if held:
                self._reserved[name] = held
                return held
            for network_id in self._pool:
                if network_id not in taken:
                    self._reserved[name] = network_id
                    return network_id
        raise EngineError(
            f"all {self.slots} agent networks are occupied, which should have "
            "been refused as a capacity error before a network was claimed"
        )

    def find(self, name):
        found = self.engine.call(
            "GET",
            "/services",
            query={"filters": json.dumps({"name": [name]})},
        )
        for item in found or []:
            if (item.get("Spec") or {}).get("Name") == name:
                return item
        return None

    def list_agents(self):
        return (
            self.engine.call(
                "GET",
                "/services",
                query={"filters": json.dumps({"label": [LABEL_PLATFORM]})},
            )
            or []
        )

    @staticmethod
    def env_of(detail):
        spec = (detail.get("Spec") or {}).get("TaskTemplate") or {}
        return list((spec.get("ContainerSpec") or {}).get("Env") or [])

    @staticmethod
    def labels_of(detail):
        return dict((detail.get("Spec") or {}).get("Labels") or {})

    def is_running(self, detail):
        mode = (detail.get("Spec") or {}).get("Mode") or {}
        if ((mode.get("Replicated") or {}).get("Replicas") or 0) < 1:
            return False
        tasks = self.engine.call(
            "GET",
            "/tasks",
            query={
                "filters": json.dumps(
                    {"service": [detail["ID"]], "desired-state": ["running"]}
                )
            },
        )
        return any(
            (task.get("Status") or {}).get("State") == "running" for task in tasks or []
        )

    @staticmethod
    def started_at(detail):
        return detail.get("UpdatedAt") or ""

    def create(self, spec, network_id):
        body = {
            "Name": spec["name"],
            "Labels": spec["labels"],
            "TaskTemplate": {
                "ContainerSpec": {
                    "Image": spec["image"],
                    "Command": spec["entrypoint"],
                    "Args": spec["cmd"],
                    "Env": spec["env"],
                    "Labels": spec["labels"],
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Source": spec["volume"],
                            "Target": spec["data"],
                        }
                    ],
                    "Privileges": {"NoNewPrivileges": True},
                },
                "Resources": {
                    "Limits": {
                        "NanoCPUs": spec["nano_cpus"],
                        "MemoryBytes": spec["memory"],
                        "Pids": spec["pids"],
                    },
                    "Reservations": {"MemoryBytes": spec["memory_reservation"]},
                },
                "Placement": {"Constraints": [self.constraint]},
                "RestartPolicy": {"Condition": "any"},
                "Networks": [{"Target": network_id, "Aliases": [spec["name"]]}],
            },
            "Mode": {"Replicated": {"Replicas": 0}},
        }
        if spec["user"]:
            body["TaskTemplate"]["ContainerSpec"]["User"] = spec["user"]
        self.engine.call("POST", "/services/create", body=body)
        return self.find(spec["name"])

    def _scale(self, detail, replicas, network_id=None):
        current = self.engine.call("GET", f"/services/{detail['ID']}")
        spec = current["Spec"]
        spec["Mode"] = {"Replicated": {"Replicas": replicas}}
        if network_id is not None:
            spec["TaskTemplate"]["Networks"] = [
                {"Target": network_id, "Aliases": [spec["Name"]]}
            ]
        self.engine.call(
            "POST",
            f"/services/{detail['ID']}/update",
            body=spec,
            query={"version": current["Version"]["Index"]},
        )
        return self.engine.call("GET", f"/services/{detail['ID']}")

    def start(self, detail, network_id=None):
        return self._scale(detail, 1, network_id)

    def stop(self, detail):
        self._scale(detail, 0)
        with self._claim:
            self._reserved.pop((detail.get("Spec") or {}).get("Name"), None)
