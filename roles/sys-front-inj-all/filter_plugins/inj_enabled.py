import sys
from pathlib import Path

from utils.roles.applications.config import get

# nocheck: project-root-import
_BASE_DIR = str(Path(__file__).resolve().parents[3])
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)


def inj_enabled_filter(
    applications: dict,
    application_id: str,
    features: list,
    prefix: str = "services",
    default: bool = False,
) -> dict:
    """
    Build a dict {feature: enabled_bool} by reading flags from:

        services.<feature>.enabled
    """
    if not isinstance(features, (list, tuple)):
        return {}

    result: dict = {}
    for f in features:
        name = str(f)
        path = f"{prefix}.{name}.enabled"

        result[name] = get(
            applications,
            application_id,
            path,
            strict=False,
            default=default,
        )

    return result


class FilterModule:
    def filters(self):
        return {
            "inj_enabled": inj_enabled_filter,
        }
