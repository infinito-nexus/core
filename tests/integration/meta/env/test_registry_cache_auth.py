from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.env.builder import build_env
from utils.env.parser import parse_static_env_with_comments
from utils.env.writer import write_dotenv
from utils.infra import INVENTORY_TEMPLATE, render_inventory

from . import PROJECT_ROOT

KEY = "INFINITO_CACHE_REGISTRY_AUTH"
DUMMY = "auth.docker.io:dummyuser:dummytoken"
ROLE = "svc-registry-cache"


def _clean_environ() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("INFINITO_")}


def _generate(repo_root: Path, credential: str | None) -> dict[str, str]:
    """
    Args:
        repo_root: directory standing in for the checkout; receives custom.env and .env.
        credential: value written to custom.env; None writes no custom.env.

    Returns:
        The generated key/value set.
    """
    if credential is not None:
        (repo_root / "custom.env").write_text(f"{KEY}={credential}\n", encoding="utf-8")
    static, comments = parse_static_env_with_comments(PROJECT_ROOT / "default.env")
    with (
        patch.dict(os.environ, _clean_environ(), clear=True),
        patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
        patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
    ):
        eb = build_env(static, repo_root, comments=comments)
    write_dotenv(eb, repo_root / ".env")
    return eb.values


def _inventory(repo_root: Path, values: dict[str, str]) -> dict:
    """
    Args:
        repo_root: directory standing in for the checkout; receives the infra
            inventory template and the host vars rendered from it.
        values: the generated key/value set.

    Returns:
        The applications block of the rendered infra inventory.
    """
    template = repo_root / INVENTORY_TEMPLATE
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(
        read_text(str(PROJECT_ROOT / INVENTORY_TEMPLATE)),
        encoding="utf-8",
    )
    return load_yaml(render_inventory(repo_root, values))["applications"]


class TestRegistryCacheAuth(unittest.TestCase):
    def test_default_is_empty_and_custom_env_sets_it(self) -> None:
        for credential, expected in ((None, ""), (DUMMY, DUMMY)):
            with (
                self.subTest(credential=credential),
                tempfile.TemporaryDirectory() as tmp,
            ):
                self.assertEqual(_generate(Path(tmp), credential).get(KEY), expected)

    def test_the_infra_inventory_hands_it_to_the_registry_cache_only(self) -> None:
        for credential, expected in ((None, ""), (DUMMY, DUMMY)):
            with (
                self.subTest(credential=credential),
                tempfile.TemporaryDirectory() as tmp,
            ):
                repo_root = Path(tmp)
                applications = _inventory(repo_root, _generate(repo_root, credential))
                proxy = applications[ROLE]["services"]["cache"]["multi_proxy"]
                self.assertEqual(proxy.pop("auth"), expected)
                self.assertNotIn(DUMMY, json.dumps(applications))


if __name__ == "__main__":
    unittest.main()
