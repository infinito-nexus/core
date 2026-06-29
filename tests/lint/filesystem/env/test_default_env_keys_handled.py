"""Every key in default.env must be wired through a handler builder.

default.env is the SPOT for static defaults. The handler builders
under ``utils/env/handlers/`` are responsible for applying each entry
as a ``setdefault`` on the EnvBuilder. If a key lives in default.env
but no handler references it, the generated ``.env`` will silently
miss the default and downstream consumers crash with an unbound
variable.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_KEY_RE = re.compile(r"^\s*(?P<key>INFINITO_[A-Z0-9_]+)\s*=")
_HANDLER_LITERAL_RE = re.compile(r"[\"'](?P<key>INFINITO_[A-Z0-9_]+)[\"']")


def _default_env_keys(path: Path) -> set[str]:
    return {
        match.group("key")
        for line in read_text(str(path)).splitlines()
        if (match := _KEY_RE.match(line)) is not None
    }


def _handler_referenced_keys(handlers_dir: Path) -> set[str]:
    keys: set[str] = set()
    for module in sorted(handlers_dir.glob("*.py")):
        if module.name == "__init__.py":
            continue
        text = read_text(str(module))
        for match in _HANDLER_LITERAL_RE.finditer(text):
            keys.add(match.group("key"))
    return keys


class TestDefaultEnvKeysHandled(unittest.TestCase):
    def test_every_default_env_key_has_a_handler(self) -> None:
        default_env_path = PROJECT_ROOT / "default.env"
        handlers_dir = PROJECT_ROOT / "utils" / "env" / "handlers"

        self.assertTrue(default_env_path.is_file(), "default.env not found")
        self.assertTrue(handlers_dir.is_dir(), "utils/env/handlers/ not found")

        declared = _default_env_keys(default_env_path)
        self.assertTrue(declared, "default.env has no INFINITO_* entries")

        referenced = _handler_referenced_keys(handlers_dir)
        missing = sorted(declared - referenced)
        if not missing:
            return

        lines = [
            f"INFINITO_* keys in default.env are not wired through any handler "
            f"({len(missing)} unhandled):",
            "",
            "default.env is the SPOT for static defaults; each key MUST be applied via setdefault by a handler in utils/env/handlers/ (typically the static-passthrough handler). Add the key to the handler's STATIC_KEYS / KEY constant so `make dotenv` materialises the default into the generated .env.",
            "",
            "Unhandled keys:",
        ]
        lines.extend(f"  {key}" for key in missing)
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
