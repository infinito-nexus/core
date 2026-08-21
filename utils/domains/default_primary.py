"""The CI/dev primary domain, read from ``default.env`` (the SPOT)."""

from __future__ import annotations

from utils.cache.files import PROJECT_ROOT
from utils.env.parser import parse_static_env


def default_domain_primary() -> str:
    """The ``INFINITO_DOMAIN`` fallback declared in ``default.env``.

    Consumers that take an explicit domain or read one from the environment
    fall back here rather than repeating the literal, so changing the CI/dev
    default is a one-line edit in ``default.env`` instead of a hunt through
    the tree.
    """
    return parse_static_env(PROJECT_ROOT / "default.env")["INFINITO_DOMAIN"]
