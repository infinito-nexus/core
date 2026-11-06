"""Test-only persona accounts and the surfaces allowed to read them."""

from __future__ import annotations

TEST_PERSONA_USERS = ("biber", "mapache")

TEST_SURFACE_BASENAMES = ("playwright.env.j2", "test.env.j2")


def is_test_surface(rel_path: str) -> bool:
    """Whether a path may read a test persona.

    Args:
        rel_path: repository-relative POSIX path.

    Returns:
        True for the Playwright and CLI test surfaces.
    """
    if rel_path.startswith(("tests/", "roles/test-")):
        return True
    parts = rel_path.split("/")
    if "files" in parts and "playwright" in parts:
        return True
    return parts[-1] in TEST_SURFACE_BASENAMES
