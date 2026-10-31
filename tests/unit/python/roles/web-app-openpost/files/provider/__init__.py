import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[7]
PACKAGE_ROOT: Path = PROJECT_ROOT / "roles/web-app-openpost/files/provider"

if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

__all__ = ["PACKAGE_ROOT", "PROJECT_ROOT"]
