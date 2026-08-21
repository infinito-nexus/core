"""Shared test fixtures for the inventory unit tests.

Kept tiny and centralised so the per-submodule test files stay focused
on their own assertions while reusing the same `DevInventorySpec`
defaults.
"""

from __future__ import annotations

from cli.administration.deploy.development.inventory import DevInventorySpec


def make_spec(**overrides) -> DevInventorySpec:
    base = {
        "inventory_dir": "/tmp/inv",
        "include": ("web-app-keycloak", "web-app-nextcloud"),
        "storage_constrained": False,
        "runtime": "dev",
    }
    base.update(overrides)
    return DevInventorySpec(**base)
