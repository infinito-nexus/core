import unittest
from pathlib import Path
from urllib.parse import urlsplit

import requests

from utils.annotations.message import warning
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

MATRIX_SERVICES: Path = PROJECT_ROOT / "roles/web-app-matrix" / ROLE_FILE_META_SERVICES

_MDAD_TIMEOUT_SECONDS = 20


def _mdad_raw_base() -> str:
    upstream = load_yaml_any(str(MATRIX_SERVICES))["matrix"]["upstream"]
    slug = urlsplit(upstream["repo"]).path.strip("/").removesuffix(".git")
    return f"https://raw.githubusercontent.com/{slug}/{upstream['ref']}"


def fetch_mdad_file(case: unittest.TestCase, path: str) -> str:
    """
    Args:
        case: the test case to skip or fail.
        path: repository-relative path inside MDAD.

    Returns:
        The file's text. A refused connection or timeout skips *case* with a
        warning annotation; any status other than 200 fails it.
    """
    url = f"{_mdad_raw_base()}/{path}"
    try:
        response = requests.get(url, timeout=_MDAD_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        warning(
            f"{url} was not checked ({type(exc).__name__}: {exc})",
            title="MDAD pin unverified",
            file=str(MATRIX_SERVICES.relative_to(PROJECT_ROOT)),
        )
        raise unittest.SkipTest(f"{url} unreachable") from exc
    case.assertEqual(
        response.status_code,
        200,
        f"{url} answered HTTP {response.status_code}; the MDAD pin no longer "
        "ships this file at this path",
    )
    return response.text


__all__ = ["MATRIX_SERVICES", "PROJECT_ROOT", "fetch_mdad_file"]
