"""Application-block validation: host_vars keys vs role contract."""

from __future__ import annotations

from .keys import recursive_keys


def compare_application_keys(applications, application_defaults, source, variants=None):
    """Variants.yml is part of the role contract: a variant overlay may
    legitimately introduce service-keys absent from meta/services.yml
    (e.g. roles/web-opt-rdr-www declares services.dashboard only in
    meta/variants.yml). Widen the allow-set to defaults ∪ union(variant
    overlays) so host_vars baked by matrix-deploy from variants.yml
    aren't flagged as "Missing default"."""
    variants = variants or {}
    errs: list[str] = []
    for app_id, conf in applications.items():
        if app_id not in application_defaults:
            errs.append(f"{source}: Unknown application '{app_id}'")
            continue
        legal_keys = recursive_keys(application_defaults[app_id])
        for variant in variants.get(app_id, []):
            legal_keys |= recursive_keys(variant)
        for key in recursive_keys(conf):
            if key.startswith("credentials"):
                continue
            if key not in legal_keys:
                errs.append(f"{source}: Missing default for {app_id}: {key}")
    return errs
