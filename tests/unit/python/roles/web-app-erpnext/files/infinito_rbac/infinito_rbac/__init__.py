from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[8]
APP_PACKAGE: Path = (
    PROJECT_ROOT / "roles/web-app-erpnext/files/python/infinito_rbac/infinito_rbac"
)

__all__ = ["APP_PACKAGE", "PROJECT_ROOT"]
