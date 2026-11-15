"""Unit test: a routine node not designated as a model node never calls the
gateway. Every routine's callable steps run with the network cut off and no
connection is attempted; a model node carries no callable, so only the
orchestrator relays it to the gateway."""

from __future__ import annotations

import socket
import unittest
import unittest.mock as mock
from contextlib import contextmanager

from agents.routines import discover, load
from agents.routines.contract import Step


class NetworkCalledError(AssertionError):
    pass


def _refuse(*_args, **_kwargs):
    raise NetworkCalledError("a non-model routine node opened a network connection")


@contextmanager
def no_network():
    """Cut every outbound connection path a gateway client would take."""
    with (
        mock.patch.object(socket.socket, "connect", _refuse),
        mock.patch.object(socket.socket, "connect_ex", _refuse),
        mock.patch.object(socket, "create_connection", _refuse),
        mock.patch.object(socket, "getaddrinfo", _refuse),
    ):
        yield


def callable_steps() -> list[tuple[str, Step]]:
    """Return ``(routine, step)`` for every step that carries a callable."""
    return [
        (name, step)
        for name in discover()
        for step in getattr(load(name), "STEPS", [])
        if getattr(step, "fn", None) is not None
    ]


class TestNonModelNodesStayOffTheGateway(unittest.TestCase):
    def test_routines_have_callable_steps(self) -> None:
        self.assertTrue(callable_steps())

    def test_no_model_node_carries_a_callable(self) -> None:
        for name, step in callable_steps():
            with self.subTest(routine=name, step=step.id):
                self.assertNotEqual(step.kind, "model")

    def test_every_callable_step_runs_without_the_network(self) -> None:
        for name, step in callable_steps():
            with self.subTest(routine=name, step=step.id), no_network():
                try:
                    step.fn({})
                except NetworkCalledError:
                    self.fail(f"{name}.{step.id} called the network")

    def test_a_node_that_calls_out_is_caught(self) -> None:
        def calls_gateway(state: dict) -> dict:
            socket.create_connection(("gateway.invalid", 443))
            return state

        rogue = Step("rogue", "calls the gateway", "decision", fn=calls_gateway)
        with no_network(), self.assertRaises(NetworkCalledError):
            rogue.fn({})


if __name__ == "__main__":
    unittest.main()
