"""Application-block validation: host_vars keys vs role contract."""

from __future__ import annotations

from utils.manager.credential_key import OVERRIDE_SECTION, SECRETS_KEY
from utils.roles.applications.dashboard import DASHBOARD_SERVICE, DISPLAY_PATH
from utils.roles.custom import CUSTOM_KEY, SOURCE_KEY, is_custom

from .keys import recursive_keys

_DASHBOARD_PATH = f"services.{DASHBOARD_SERVICE}"


def _declares_custom_role(app_id: str, key: str) -> bool:
    return is_custom(app_id) and key.split(".", 1)[0] in (CUSTOM_KEY, SOURCE_KEY)


def compare_application_keys(applications, application_defaults, source, variants=None):
    """Variants.yml is part of the role contract: a variant overlay may
    legitimately introduce service-keys absent from meta/services.yml
    (e.g. roles/web-opt-rdr-www declares services.dashboard only in
    meta/variants.yml). Widen the allow-set to defaults ∪ union(variant
    overlays) so host_vars baked by matrix-deploy from variants.yml
    aren't flagged as "Missing default".

    ``custom`` and ``source`` of a custom role are the inventory's
    declaration of where the role comes from, not role settings, so no
    role default carries them.

    ``services.dashboard.display`` is legal wherever the role contract
    declares ``services.dashboard``: absent means shown, so no role
    default carries it."""
    variants = variants or {}
    errs: list[str] = []
    for app_id, conf in applications.items():
        if app_id not in application_defaults:
            errs.append(f"{source}: Unknown application '{app_id}'")
            continue
        legal_keys = recursive_keys(application_defaults[app_id])
        for variant in variants.get(app_id, []):
            legal_keys |= recursive_keys(variant)
        if _DASHBOARD_PATH in legal_keys:
            legal_keys.add(DISPLAY_PATH)
        for key in recursive_keys(conf):
            if key == SECRETS_KEY or key.startswith(OVERRIDE_SECTION):
                continue
            if _declares_custom_role(app_id, key):
                continue
            if key not in legal_keys:
                errs.append(f"{source}: Missing default for {app_id}: {key}")
    return errs
