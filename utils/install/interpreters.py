"""Interpreter provisioning for the unit suites, baked into the image."""

from __future__ import annotations

from utils.install.php import ensure_php_toolchain
from utils.install.ruby import ensure_ruby_present
from utils.install.system_pkg import ensure_command_present

LUA_INTERPRETER = "luajit"


def ensure_interpreters_present() -> None:
    """Install the interpreters the PHP, Ruby and rendered-Lua suites run on.

    Raises:
        RuntimeError: an interpreter is still absent after the install attempt.
    """
    ensure_php_toolchain()
    ensure_ruby_present()
    ensure_command_present(LUA_INTERPRETER)


if __name__ == "__main__":
    ensure_interpreters_present()
