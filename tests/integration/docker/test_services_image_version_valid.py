from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

from utils.docker.image.ref import is_valid_image_name

# Docker tag (version)
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def _safe_mapping(obj: Any) -> Dict[str, Any]:
    return obj if isinstance(obj, dict) else {}


def _iter_role_config_files(repo_root: Path) -> List[Path]:
    roles_dir = repo_root / "roles"
    if not roles_dir.is_dir():
        return []
    return sorted(roles_dir.glob("*/meta/services.yml"))


def _extract_services(cfg: Dict[str, Any]) -> Dict[str, Any]:
    # Per req-008 the file root of meta/services.yml IS the services
    # map (no `compose.services` wrapper).
    return _safe_mapping(cfg)


def _iter_declared_fields(
    services: Dict[str, Any],
) -> Iterable[Tuple[str, str, Any]]:
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
    if not isinstance(version, str):
        return False
    version = version.strip()
    if not version or " " in version:
        return False
    return TAG_RE.fullmatch(version) is not None


class TestDockerServicesImageVersionValid(unittest.TestCase):
    def test_declared_docker_service_image_and_version_are_valid(self) -> None:
        """
        Rules:
        - `image` is OPTIONAL → only validated if present
        - `version` is OPTIONAL → only validated if present
        - No coupling required between image/version
        """
        repo_root = Path(__file__).resolve().parents[3]
        failures: List[str] = []

        config_files = _iter_role_config_files(repo_root)
        self.assertTrue(
            config_files,
            f"No role config files found under: {repo_root / 'roles' / '*/meta/services.yml'}",
        )

        for cfg_path in config_files:
            with cfg_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            cfg = _safe_mapping(data)
            services = _extract_services(cfg)

            for svc_name, field, value in _iter_declared_fields(services):
                if field == "image" and not _is_valid_image(value):
                    failures.append(
                        f"{cfg_path}: services.{svc_name}.image invalid: {value!r}"
                    )

                if field == "version" and not _is_valid_version(value):
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
