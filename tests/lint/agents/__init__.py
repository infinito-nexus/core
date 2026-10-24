"""Lint catalogue for the agents/ tree: the L-numbered static checks.

Each lint is a pure ``check(agents_dir)`` that returns a list of problem
strings, plus a unittest TestCase proving the real tree passes and a
deliberately broken fixture fails. The checks take the agents directory as an
argument so the same code runs against the real tree and against a temporary
red fixture.
"""

from __future__ import annotations

from pathlib import Path

from utils.cache.yaml import load_yaml_any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = PROJECT_ROOT / "agents"
ROLES_DIR = AGENTS_DIR / "roles"

REQUIRED_AGENT_FIELDS = (
    "runtime",
    "lifecycle",
    "owner",
    "repositories",
    "firewall_roles",
    "skills",
    "models",
    "keepass",
    "write_enabled",
    "triggers",
    "quotas",
    "credentials",
)
RUNTIMES = ("hermes", "openclaw", "claude-code")
LIFECYCLES = ("on_demand", "always_on")
KEEPASS_MODES = ("broker", "agent")
LOCAL_ONLY_ROLES = ("support", "planner", "operator")


def role_names(roles_dir: Path) -> list[str]:
    """Return the role directory names under ``roles_dir``."""
    if not roles_dir.is_dir():
        return []
    return sorted(p.name for p in roles_dir.iterdir() if p.is_dir())


def load(path: Path):
    """Return the parsed single YAML document at ``path`` (``None`` if absent)."""
    if not path.is_file():
        return None
    return load_yaml_any(str(path), default_if_missing={})
