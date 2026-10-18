from __future__ import annotations

import sys
import threading
import unittest

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python"))

import engine
import swarm

SPEC = {
    "name": "agent-hermes-1",
    "network": "agent-hermes-1",
    "volume": "agent-hermes-1",
    "image": "hermes:1",
    "entrypoint": ["/bin/sh", "-c", 'exec "$@"', "agent"],
    "cmd": ["gateway"],
    "env": ["A=1"],
    "labels": {engine.LABEL_OWNER: "u1"},
    "data": "/opt/data",
    "user": "",
    "nano_cpus": 1,
    "memory": 2,
    "memory_reservation": 1,
    "pids": 3,
}


class RecordingEngine:
    def __init__(self):
        self.calls = []

    def call(self, method, path, body=None, query=None, expect=(200,)):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/services":
            return []
        return {"Id": "abc", "Name": "/agent"}


class PoolEngine:
    """
    Args:
        agents: service details ``/services`` answers with.
        attached: networks the broker's own service spec already carries.
    """

    def __init__(self, agents=(), attached=()):
        self.agents = list(agents)
        self.attached = list(attached)
        self.updates = []

    def ensure_network(self, name, driver, labels):
        return f"net-{name}"

    def call(self, method, path, body=None, query=None, expect=(200,)):
        if path.endswith("/json"):
            return {"Config": {"Labels": {"com.docker.swarm.service.id": "svc-broker"}}}
        if path == "/services":
            return self.agents
        if path == "/services/svc-broker":
            return {
                "Spec": {
                    "Name": "agent-broker",
                    "TaskTemplate": {"Networks": list(self.attached)},
                },
                "Version": {"Index": 7},
            }
        if path == "/tasks":
            return [{"Status": {"State": "running"}}]
        if path.endswith("/update"):
            self.updates.append(body)
            return None
        if path.startswith("/services/"):
            wanted = path.removeprefix("/services/")
            for detail in self.agents:
                if detail["ID"] == wanted:
                    return {"Spec": detail["Spec"], "Version": {"Index": 1}}
            raise AssertionError(path)
        raise AssertionError(path)


def _running_agent(name, network_id):
    return {
        "ID": name,
        "Spec": {
            "Name": name,
            "Mode": {"Replicated": {"Replicas": 1}},
            "TaskTemplate": {"Networks": [{"Target": network_id}]},
        },
    }


class TestSwarmBackendPool(unittest.TestCase):
    def test_the_broker_joins_every_pool_network_through_its_own_spec(self):
        """A service task cannot be attached at runtime, so the pool has to
        reach the broker through a spec update carrying the agents' alias."""
        fake = PoolEngine()
        swarm.SwarmBackend(fake, "c", "p", 2).ensure_pool("broker-1", "agent-broker")
        self.assertEqual(len(fake.updates), 1)
        self.assertEqual(
            fake.updates[0]["TaskTemplate"]["Networks"],
            [
                {"Target": "net-p-0", "Aliases": ["agent-broker"]},
                {"Target": "net-p-1", "Aliases": ["agent-broker"]},
            ],
        )

    def test_an_already_attached_broker_is_not_rescheduled_again(self):
        """The spec update restarts the broker task, so a converged spec must
        leave it alone rather than restart it on every start-up."""
        fake = PoolEngine(attached=[{"Target": "net-p-0"}, {"Target": "net-p-1"}])
        swarm.SwarmBackend(fake, "c", "p", 2).ensure_pool("broker-1", "agent-broker")
        self.assertEqual(fake.updates, [])

    def test_a_running_agent_keeps_its_network_to_itself(self):
        """Two agents on one network would reach each other, so a slot a
        running agent holds is never handed to another."""
        fake = PoolEngine(agents=[_running_agent("agent-hermes-u1", "net-p-0")])
        backend = swarm.SwarmBackend(fake, "c", "p", 2)
        backend.ensure_pool("broker-1", "agent-broker")
        self.assertEqual(
            backend.network_for("agent-hermes-u2", {}, "broker-1", "agent-broker"),
            "net-p-1",
        )

    def test_a_scaled_out_broker_is_refused(self):
        """A second replica claims from its own memory, so it would hand a
        network another replica already gave away."""
        fake = PoolEngine()
        fake.attached = [{"Target": "net-p-0"}, {"Target": "net-p-1"}]
        backend = swarm.SwarmBackend(fake, "c", "p", 2)
        original = fake.call

        def scaled(method, path, body=None, query=None, expect=(200,)):
            answer = original(method, path, body, query, expect)
            if path == "/services/svc-broker":
                answer["Spec"]["Mode"] = {"Replicated": {"Replicas": 2}}
            return answer

        fake.call = scaled
        with self.assertRaises(engine.EngineError):
            backend.ensure_pool("broker-1", "agent-broker")

    def test_two_owners_starting_at_once_get_different_networks(self):
        """The claim is what keeps two agents off one network, so two first
        starts racing each other must not be handed the same slot."""
        fake = PoolEngine()
        backend = swarm.SwarmBackend(fake, "c", "p", 4)
        backend.ensure_pool("broker-1", "agent-broker")
        claimed = []
        barrier = threading.Barrier(4)

        def claim(index):
            barrier.wait()
            claimed.append(
                backend.network_for(
                    f"agent-hermes-u{index}", {}, "broker-1", "agent-broker"
                )
            )

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(claimed), sorted(set(claimed)))
        self.assertEqual(len(claimed), 4)

    def test_a_service_scaled_up_before_its_task_runs_holds_its_network(self):
        """A claim has to count from the replica count the engine already
        recorded, or the next caller is handed the same network while the
        first task is still starting."""
        fake = PoolEngine(agents=[_running_agent("agent-hermes-u1", "net-p-0")])
        fake.agents[0]["Spec"]["TaskTemplate"]["Networks"] = [{"Target": "net-p-0"}]
        backend = swarm.SwarmBackend(fake, "c", "p", 2)
        backend.ensure_pool("broker-1", "agent-broker")
        self.assertEqual(
            backend.network_for("agent-hermes-u2", {}, "broker-1", "agent-broker"),
            "net-p-1",
        )

    def test_a_stopped_agent_releases_its_network(self):
        """A slot a stopped agent kept would shrink the pool below the agent
        count the broker is configured to run."""
        agent = _running_agent("agent-hermes-u1", "net-p-0")
        fake = PoolEngine(agents=[agent])
        backend = swarm.SwarmBackend(fake, "c", "p", 1)
        backend.ensure_pool("broker-1", "agent-broker")
        backend.network_for("agent-hermes-u1", {}, "broker-1", "agent-broker")
        agent["Spec"]["Mode"]["Replicated"]["Replicas"] = 0
        backend.stop(agent)
        self.assertEqual(
            backend.network_for("agent-hermes-u2", {}, "broker-1", "agent-broker"),
            "net-p-0",
        )

    def test_an_agent_that_holds_a_slot_is_given_it_back(self):
        """A second request of the same owner must not move the agent onto a
        second network while its task is running."""
        fake = PoolEngine(agents=[_running_agent("agent-hermes-u1", "net-p-1")])
        backend = swarm.SwarmBackend(fake, "c", "p", 2)
        backend.ensure_pool("broker-1", "agent-broker")
        self.assertEqual(
            backend.network_for("agent-hermes-u1", {}, "broker-1", "agent-broker"),
            "net-p-1",
        )


class TestSwarmBackend(unittest.TestCase):
    def test_a_service_is_placed_on_the_sandbox_nodes_and_starts_scaled_down(self):
        fake = RecordingEngine()
        swarm.SwarmBackend(
            fake, "node.labels.kata-capable == true", "agent-broker-agent", 4
        ).create(SPEC, "net-1")
        body = next(
            body for method, path, body in fake.calls if path == "/services/create"
        )
        self.assertEqual(
            body["TaskTemplate"]["Placement"]["Constraints"],
            ["node.labels.kata-capable == true"],
        )
        self.assertEqual(body["Mode"], {"Replicated": {"Replicas": 0}})


if __name__ == "__main__":
    unittest.main()
