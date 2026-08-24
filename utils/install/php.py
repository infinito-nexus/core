"""PHP toolchain provisioning for the PHP unit suite."""

from __future__ import annotations

import subprocess

from utils import PROJECT_ROOT
from utils.install.primitives import log
from utils.install.system_pkg import (
    ensure_command_present,
    ensure_php_extension_present,
)

_PHPUNIT = PROJECT_ROOT / "vendor" / "bin" / "phpunit"

_PHPUNIT_EXTENSIONS = ("dom", "mbstring", "xmlwriter")


def ensure_php_toolchain() -> None:
    """Install the PHP interpreter, Composer and the extensions PHPUnit needs.

    ``phpunit/phpunit ^11`` declares ``_PHPUNIT_EXTENSIONS`` as platform
    requirements and Composer refuses to resolve the vendor tree without them,
    so they are part of the toolchain rather than of the suite consuming it.
    A distro ships them as packages separate from the interpreter, which is why
    a present ``php`` binary does not imply they are there.

    Raises:
        RuntimeError: php, composer or one of the extensions is still absent.
    """
    ensure_command_present("php")
    ensure_command_present("composer")
    for extension in _PHPUNIT_EXTENSIONS:
        ensure_php_extension_present(extension)


def ensure_php_present() -> None:
    """Install the PHP toolchain and the Composer vendor tree.

    Raises:
        RuntimeError: php, composer or phpunit is still absent afterwards.
        subprocess.CalledProcessError: ``composer install`` failed.
    """
    ensure_php_toolchain()

    if not _PHPUNIT.is_file():
        log("phpunit missing; running composer install.")
        subprocess.run(
            ["composer", "install", "--no-interaction", "--no-progress"],
            cwd=PROJECT_ROOT,
            check=True,
        )

    if not _PHPUNIT.is_file():
        raise RuntimeError(f"{_PHPUNIT} missing after composer install")


if __name__ == "__main__":
    ensure_php_present()
