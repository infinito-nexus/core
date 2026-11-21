"""Unit test: one test drives the Matrix, email and Zammad implementations of
the channel contract through the same ``envelope`` call; each addresses the
account, carries the text, and refuses a session id or a malformed name."""

from __future__ import annotations

import unittest

from utils.orchestrator.channels import (
    EmailChannel,
    MatrixChannel,
    ZammadChannel,
    dispatch,
    is_addressable,
)

CHANNELS = (
    MatrixChannel(homeserver="matrix.infinito.example"),
    EmailChannel(domain="infinito.example", sender="orch0main@infinito.example"),
    ZammadChannel(group="Agents"),
)
EXPECTED_TO = {
    "matrix": "@mant0alice:matrix.infinito.example",
    "email": "mant0alice@infinito.example",
    "zammad": "mant0alice",
}
REFUSED = ("ffb7d068-2d34-44a4-b22a-95cc880a6dc8", "agent-hermes-9f1e", "al")


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    return str(value)


class TestChannelContract(unittest.TestCase):
    def test_every_channel_delivers_through_the_same_interface(self):
        for channel in CHANNELS:
            with self.subTest(channel=channel.name):
                request = channel.envelope("mant0alice", "Run 4711 is red.\nDetails")
                self.assertEqual(request["channel"], channel.name)
                self.assertEqual(request["to"], EXPECTED_TO[channel.name])
                self.assertIn("Run 4711 is red.\nDetails", _flatten(request))

    def test_every_channel_refuses_what_is_not_an_account(self):
        for channel in CHANNELS:
            for recipient in REFUSED:
                with (
                    self.subTest(channel=channel.name, recipient=recipient),
                    self.assertRaises(ValueError),
                ):
                    channel.envelope(recipient, "hello")

    def test_a_trailing_newline_never_reaches_a_header(self):
        for recipient in ("biber\n", "mant0alice\n"):
            with self.subTest(recipient=recipient):
                self.assertFalse(is_addressable(recipient))
                for channel in CHANNELS:
                    with self.assertRaises(ValueError):
                        channel.envelope(recipient, "hello")

    def test_a_human_username_is_addressable_on_every_channel(self):
        self.assertTrue(is_addressable("biber"))
        for channel in CHANNELS:
            with self.subTest(channel=channel.name):
                self.assertIn("biber", channel.envelope("biber", "hi")["to"])

    def test_dispatch_takes_the_first_channel_in_priority_order(self):
        self.assertEqual(dispatch(list(CHANNELS), "biber", "hi")["channel"], "matrix")
        self.assertEqual(
            dispatch(list(CHANNELS[1:]), "biber", "hi")["channel"], "email"
        )
        with self.assertRaises(ValueError):
            dispatch([], "biber", "hi")


REMOTE = "https://live.infinito.example"


class TestRemoteInstanceChannel(unittest.TestCase):
    def test_a_remote_channel_with_credentials_carries_the_message(self):
        remote = MatrixChannel(
            homeserver="matrix.live.example", remote=REMOTE, credential="kdbx:matrix"
        )
        request = dispatch([CHANNELS[0], remote], "mant0alice", "hi")
        self.assertEqual(request["to"], "@mant0alice:matrix.live.example")

    def test_without_credentials_the_local_channel_is_used(self):
        remote = MatrixChannel(homeserver="matrix.live.example", remote=REMOTE)
        request = dispatch([remote, *CHANNELS], "mant0alice", "hi")
        self.assertEqual(request["to"], "@mant0alice:matrix.infinito.example")
        with self.assertRaises(ValueError):
            dispatch([remote], "mant0alice", "hi")


if __name__ == "__main__":
    unittest.main()
