"""Unit tests for :mod:`utils.install.node`."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.install import node as node_mod


class TestEnsureNodePresent(unittest.TestCase):
    def test_delegates_to_the_shared_provisioner(self) -> None:
        with mock.patch.object(node_mod, "ensure_command_present") as ensure:
            node_mod.ensure_node_present()
        ensure.assert_called_once_with("node")

    def test_propagates_the_hard_failure(self) -> None:
        with (
            mock.patch.object(
                node_mod, "ensure_command_present", side_effect=RuntimeError("boom")
            ),
            self.assertRaises(RuntimeError),
        ):
            node_mod.ensure_node_present()


if __name__ == "__main__":
    unittest.main()
