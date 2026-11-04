from pathlib import Path

from tests.utils.django_stubs import AUTH_USER_MODEL

PROJECT_ROOT: Path = Path(__file__).resolve().parents[8]
APP = PROJECT_ROOT / "roles/web-app-baserow/files/sso/infinito_sso_subject"

__all__ = ["APP", "AUTH_USER_MODEL", "PROJECT_ROOT"]
