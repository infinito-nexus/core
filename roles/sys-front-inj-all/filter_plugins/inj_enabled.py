import os
import sys

from utils.applications.config import get

# Allow imports from utils (same trick as your config filter)
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MODULE_UTILS_DIR = os.path.join(_BASE_DIR, "utils")
for _p in (_BASE_DIR, _MODULE_UTILS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


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


class FilterModule(object):
    def filters(self):
        return {
            "inj_enabled": inj_enabled_filter,
        }
