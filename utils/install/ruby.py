"""Ruby runtime provisioning for the Ruby unit suite."""

from __future__ import annotations

from utils.install.system_pkg import ensure_command_present


def ensure_ruby_present() -> None:
    """Install the Ruby interpreter through the system package manager.

    Raises:
        RuntimeError: ruby is still absent after the install attempt.
    """
    ensure_command_present("ruby")


if __name__ == "__main__":
    ensure_ruby_present()
