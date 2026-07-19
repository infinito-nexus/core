from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_role_local_module_utils():
    """
    Load utils/kcadm_json.py deterministically from disk, without relying
    on sys.path/ansible.module_utils resolution.

    No try/except on purpose: errors should fail hard & loud.
    """
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent.parent
    mod_path = project_root / "utils" / "kcadm_json.py"

    spec = importlib.util.spec_from_file_location(
        "web_app_keycloak_kcadm_json",
        str(mod_path),
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {mod_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_kcadm_json_mod = _load_role_local_module_utils()
json_from_noisy_stdout = _kcadm_json_mod.json_from_noisy_stdout


class FilterModule:
    def filters(self):
        return {"kcadm_json": self.kcadm_json}

    def kcadm_json(self, stdout: Any) -> Any:
        return json_from_noisy_stdout(stdout)
