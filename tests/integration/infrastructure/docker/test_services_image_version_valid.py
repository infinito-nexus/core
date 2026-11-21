from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_str
from utils.docker.image.pin import DIGEST_PREFIX
from utils.docker.image.ref import is_valid_image_name
from utils.roles.custom import resolve_role_version
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
DIGEST_RE = re.compile(rf"^{re.escape(DIGEST_PREFIX)}[0-9a-f]{{64}}$")


def _safe_mapping(obj: Any) -> dict[str, Any]:
    return obj if isinstance(obj, dict) else {}


def _iter_role_config_files(repo_root: Path) -> list[Path]:
    roles_dir = repo_root / "roles"
    if not roles_dir.is_dir():
        return []
    return sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}"))


def _extract_services(cfg: dict[str, Any]) -> dict[str, Any]:
    return _safe_mapping(cfg)


def _iter_declared_fields(
    services: dict[str, Any],
) -> Iterable[tuple[str, str, Any]]:
    """
    Yield (service_name, field_name, value) for each declared field
    where field_name ∈ {"image", "version"}.
    """
    for svc_name, svc_cfg in services.items():
        svc_map = _safe_mapping(svc_cfg)
        for field in ("image", "version"):
            if field in svc_map:
                yield svc_name, field, svc_map.get(field)


def _is_valid_image(image: Any) -> bool:
    return is_valid_image_name(image)


def _is_valid_version(version: Any) -> bool:
    """
    Args:
        version: the ``version:`` value of a service.

    Returns:
        Whether it is a tag or a ``sha256`` digest, the two pins
        :mod:`utils.docker.image.pin` joins to an image name.
    """
    if not isinstance(version, str):
        return False
    version = version.strip()
    if not version or " " in version:
        return False
    return (
        TAG_RE.fullmatch(version) is not None
        or DIGEST_RE.fullmatch(version) is not None
    )


class TestVersionShapes(unittest.TestCase):
    def test_a_tag_and_a_digest_are_valid_pins(self) -> None:
        for version in ("24-alpine", "v1.2.3", f"{DIGEST_PREFIX}{'a' * 64}"):
            with self.subTest(version=version):
                self.assertTrue(_is_valid_version(version))

    def test_negative_control_a_malformed_pin_is_invalid(self) -> None:
        for version in (
            f"{DIGEST_PREFIX}{'a' * 63}",
            f"{DIGEST_PREFIX}{'A' * 64}",
            f"{DIGEST_PREFIX}xyz",
            "sha512:" + "a" * 128,
            "1.2 3",
            "",
        ):
            with self.subTest(version=version):
                self.assertFalse(_is_valid_version(version))


class TestDockerServicesImageVersionValid(unittest.TestCase):
    def test_declared_docker_service_image_and_version_are_valid(self) -> None:
        """
        Rules:
        - `image` is OPTIONAL → only validated if present
        - `version` is OPTIONAL → only validated if present
        - No coupling required between image/version
        """
        repo_root = PROJECT_ROOT
        failures: list[str] = []

        config_files = _iter_role_config_files(repo_root)
        self.assertTrue(
            config_files,
            f"No role config files found under: {repo_root / 'roles' / f'*/{ROLE_FILE_META_SERVICES}'}",
        )

        for cfg_path in config_files:
            with cfg_path.open("r", encoding="utf-8") as f:
                data = load_yaml_str(f) or {}

            cfg = _safe_mapping(data)
            services = _extract_services(cfg)

            for svc_name, field, value in _iter_declared_fields(services):
                if field == "image" and not _is_valid_image(value):
                    failures.append(
                        f"{cfg_path}: services.{svc_name}.image invalid: {value!r}"
                    )

                if field == "version" and not _is_valid_version(
                    resolve_role_version(value, repo_root / "roles")
                    if isinstance(value, str)
                    else value
                ):
                    failures.append(
                        f"{cfg_path}: services.{svc_name}.version invalid: {value!r}"
                    )

        if failures:
            self.fail(
                "Invalid services image/version entries found:\n"
                + "\n".join(f"- {x}" for x in failures)
            )


if __name__ == "__main__":
    unittest.main()
