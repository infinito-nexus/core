from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

IMAGE = "rpardini/docker-registry-proxy:0.6.5"
IMAGE_ENTRYPOINT = "/entrypoint.sh"
WRAPPER = PROJECT_ROOT / "compose" / "registry-cache" / "entrypoint.sh"
IMAGE_CONF = "/etc/nginx/conf.d/cache_max_size.conf"
UPSTREAM_0_6_5 = (
    "#! /bin/bash\n"
    "set -Eeuo pipefail\n"
    "CACHE_MAX_SIZE=${CACHE_MAX_SIZE:-32g}\n"
    'echo "proxy_cache_path /docker_mirror_cache levels=1:2 max_size=$CACHE_MAX_SIZE inactive=60d '
    'keys_zone=cache:10m use_temp_path=off;" > /etc/nginx/conf.d/cache_max_size.conf\n'
)
DOTENV = {
    "INFINITO_CACHE_REGISTRY_MAX_SIZE": "40g",
    "INFINITO_CACHE_MAX_IDLE_DAYS": "30",
    "INFINITO_CACHE_REGISTRIES": "ghcr.io",
}
_REQUIRED = re.compile(r"\$\{(?P<key>[A-Z0-9_]+):\?[^}]*\}")
_PROXY_CACHE_PATH = re.compile(r"^proxy_cache_path\s+(?P<args>[^;]+);", re.MULTILINE)


def _service() -> dict:
    return load_yaml_any(str(PROJECT_ROOT / "compose" / "cache.override.yml"))[
        "services"
    ]["registry-cache"]


def _environment(dotenv: dict[str, str]) -> dict[str, str]:
    """Args:
        dotenv: the values `.env` holds.

    Returns:
        The service environment with every required ``${KEY:?message}`` reference resolved.
    """
    return {
        key: _REQUIRED.sub(lambda match: dotenv[match.group("key")], str(value))
        for key, value in _service()["environment"].items()
    }


def _start(
    dotenv: dict[str, str], image_entrypoint: str, wrapped: bool
) -> tuple[int, dict[str, str], str]:
    """Args:
        dotenv: the values `.env` holds.
        image_entrypoint: the text of the image's own entrypoint.
        wrapped: start it through the service entrypoint wrapper instead of directly.

    Returns:
        The exit code, the arguments of the ``proxy_cache_path`` line the start wrote, and its stderr.
    """
    with tempfile.TemporaryDirectory() as tmp:
        conf = Path(tmp) / "cache_max_size.conf"
        original = Path(tmp) / "entrypoint.sh"
        original.write_text(image_entrypoint.replace(IMAGE_CONF, str(conf)))
        command = (
            ["bash", str(WRAPPER), str(original)]
            if wrapped
            else ["bash", str(original)]
        )
        done = subprocess.run(
            command,
            env={"PATH": os.environ["PATH"], **_environment(dotenv)},
            capture_output=True,
            text=True,
            check=False,
        )
        written = read_text(str(conf)) if conf.exists() else ""
    match = _PROXY_CACHE_PATH.search(written)
    args = match.group("args").split() if match else []
    parsed = dict(token.split("=", 1) for token in args if "=" in token)
    return done.returncode, parsed, done.stderr


class TestRegistryCacheBounds(unittest.TestCase):
    def test_the_effective_nginx_cache_carries_the_cap_and_the_idle_window(
        self,
    ) -> None:
        code, args, _ = _start(DOTENV, UPSTREAM_0_6_5, True)
        self.assertEqual(code, 0)
        self.assertEqual([args.get("max_size"), args.get("inactive")], ["40g", "30d"])

    def test_both_bounds_follow_the_environment(self) -> None:
        dotenv = {
            **DOTENV,
            "INFINITO_CACHE_REGISTRY_MAX_SIZE": "12g",
            "INFINITO_CACHE_MAX_IDLE_DAYS": "7",
        }
        _, args, _ = _start(dotenv, UPSTREAM_0_6_5, True)
        self.assertEqual([args.get("max_size"), args.get("inactive")], ["12g", "7d"])

    def test_the_image_entrypoint_alone_keeps_its_sixty_days(self) -> None:
        _, args, _ = _start(DOTENV, UPSTREAM_0_6_5, False)
        self.assertEqual([args.get("max_size"), args.get("inactive")], ["40g", "60d"])

    def test_an_image_without_the_replaced_line_fails_before_nginx_starts(self) -> None:
        code, args, stderr = _start(
            DOTENV, UPSTREAM_0_6_5.replace("inactive=60d", "inactive=90d"), True
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(args, {})
        self.assertIn("check the pinned image before bounding its cache", stderr)

    def test_the_service_runs_the_image_entrypoint_through_the_wrapper(self) -> None:
        service = _service()
        self.assertEqual(service["image"], IMAGE)
        target = service["entrypoint"][0]
        self.assertEqual(service["entrypoint"][1:], [IMAGE_ENTRYPOINT])
        binds = [
            v
            for v in service["volumes"]
            if isinstance(v, dict) and v.get("target") == target
        ]
        self.assertEqual(len(binds), 1)
        self.assertTrue(binds[0]["read_only"])
        self.assertEqual((PROJECT_ROOT / binds[0]["source"]).resolve(), WRAPPER)
        self.assertTrue(os.access(WRAPPER, os.X_OK))


if __name__ == "__main__":
    unittest.main()
