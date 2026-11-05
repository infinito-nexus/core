from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.render import CONSUMER, cache_consumer_yml
from utils.env.builder import build_env
from utils.env.parser import parse_static_env_with_comments
from utils.env.writer import write_dotenv

from . import PROJECT_ROOT

KEY = "INFINITO_CACHE_REGISTRY_AUTH"
DUMMY = "auth.docker.io:dummyuser:dummytoken"
SERVICE = "registry-cache"


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


def _render(repo_root: Path) -> dict:
    """
    Args:
        repo_root: project directory holding the generated .env; receives the consumer file.

    Returns:
        The rendered compose configuration.
    """
    (repo_root / CONSUMER).write_text(cache_consumer_yml(), encoding="utf-8")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(repo_root),
            "--env-file",
            str(repo_root / ".env"),
            "-f",
            str(PROJECT_ROOT / "compose.yml"),
            "-f",
            str(PROJECT_ROOT / "compose" / "cache.override.yml"),
            "config",
            "--format",
            "json",
        ],
        env=_clean_environ(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"docker compose config failed: {result.stderr}")
    return json.loads(result.stdout)


class TestRegistryCacheAuth(unittest.TestCase):
    def test_default_is_empty_and_custom_env_sets_it(self) -> None:
        for credential, expected in ((None, ""), (DUMMY, DUMMY)):
            with (
                self.subTest(credential=credential),
                tempfile.TemporaryDirectory() as tmp,
            ):
                self.assertEqual(_generate(Path(tmp), credential).get(KEY), expected)

    def test_compose_hands_it_to_the_registry_cache_only(self) -> None:
        probe = shutil.which("docker")
        if (
            probe is None
            or subprocess.run(
                [probe, "compose", "version"], capture_output=True, check=False
            ).returncode
        ):
            self.skipTest("docker compose is not available")
        for credential, expected in ((None, ""), (DUMMY, DUMMY)):
            with (
                self.subTest(credential=credential),
                tempfile.TemporaryDirectory() as tmp,
            ):
                repo_root = Path(tmp)
                _generate(repo_root, credential)
                services = _render(repo_root)["services"]
                self.assertEqual(
                    services[SERVICE]["environment"]["AUTH_REGISTRIES"], expected
                )
                leaking = sorted(
                    name
                    for name, service in services.items()
                    if name != SERVICE and DUMMY in json.dumps(service)
                )
                self.assertEqual(leaking, [])


if __name__ == "__main__":
    unittest.main()
