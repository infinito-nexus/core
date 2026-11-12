from __future__ import annotations

import unittest

from utils import networks
from utils.networks import attachments


class TestStreamRelayName(unittest.TestCase):
    def test_the_topology_name_is_stream_relay(self):
        self.assertEqual("stream_relay", networks.STREAM_RELAY)

    def test_attachments_uses_the_package_name(self):
        self.assertIs(networks.STREAM_RELAY, attachments.STREAM_RELAY)


if __name__ == "__main__":
    unittest.main()
