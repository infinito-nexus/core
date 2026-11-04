from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[5]
ROLE_DIR: Path = PROJECT_ROOT / "roles" / "sys-preflight"

__all__ = ["PROJECT_ROOT", "ROLE_DIR"]
