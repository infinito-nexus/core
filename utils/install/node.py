"""Node.js runtime provisioning for the JavaScript unit suite."""

from __future__ import annotations

from utils.install.system_pkg import ensure_command_present


def ensure_node_present() -> None:
    """Install the Node.js runtime through the system package manager.

    Raises:
        RuntimeError: node is still absent after the install attempt.
    """
    ensure_command_present("node")


if __name__ == "__main__":
    ensure_node_present()
