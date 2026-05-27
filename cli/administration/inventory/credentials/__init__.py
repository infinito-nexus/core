"""Public API of the credentials CLI.

The package is split by concern:
- ``vault``: vault block construction + detection
- ``overrides``: ``--set`` parsing + per-key resolution
- ``emit``: recursive credentials emission into ruamel CommentedMaps
- ``prompts``: interactive operator prompts
- ``__main__``: argparse + orchestration
"""

from __future__ import annotations

from .__main__ import main
from .emit import emit_credentials, ensure_map
from .overrides import override_for, parse_overrides
from .prompts import ask_for_confirmation
from .vault import is_vault_encrypted, to_vault_block

__all__ = [
    "ask_for_confirmation",
    "emit_credentials",
    "ensure_map",
    "is_vault_encrypted",
    "main",
    "override_for",
    "parse_overrides",
    "to_vault_block",
]
