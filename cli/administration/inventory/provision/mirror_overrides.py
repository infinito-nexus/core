from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any

from .ruamel_io import dump_document, ensure_map, load_document

if TYPE_CHECKING:
    from pathlib import Path

    from ruamel.yaml.comments import CommentedMap


def _is_blank(val: object) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        return not val.strip()
    return False


def _get_policy(svc_doc: CommentedMap) -> str:
    """
    Read mirror policy from existing host_vars service node.
    Allowed: force | skip | if_missing
    Default: if_missing
    """
    raw = svc_doc.get("mirror_policy")
    if raw is None:
        return "if_missing"
    if not isinstance(raw, str):
        return "if_missing"
    policy = raw.strip().lower()
    if policy in {"force", "skip", "if_missing"}:
        return policy
    return "if_missing"


def apply_mirror_overrides(host_vars_file: Path, mirrors_file: Path) -> None:
    """
    Apply image mirror overrides to host_vars.

    See docs/contributing/artefact/mirror.md for the full architecture, format,
    and mirror_policy documentation.
    """
    if not mirrors_file.exists():
        raise SystemExit(f"Mirrors file not found: {mirrors_file}")

    try:
        mirrors_raw = load_yaml_any(str(mirrors_file), default_if_missing={}) or {}
    except Exception as exc:
        raise SystemExit(f"Failed to load mirrors file {mirrors_file}: {exc}") from exc

    if not isinstance(mirrors_raw, dict):
        raise SystemExit(
            f"Mirrors file must contain a mapping at top-level: {mirrors_file}"
        )

    mirrors_apps = mirrors_raw.get("applications", {}) or {}
    has_applications = isinstance(mirrors_apps, dict) and bool(mirrors_apps)
    if not has_applications:
        return

    doc = load_document(host_vars_file)
    changed = False

    if has_applications:
        apps_doc = ensure_map(doc, "applications")
        for app_id, app_block in mirrors_apps.items():
            if not isinstance(app_block, dict):
                continue

            services = app_block.get("services") or {}
            if not isinstance(services, dict):
                continue

            app_doc = ensure_map(apps_doc, str(app_id))
            services_doc = ensure_map(app_doc, "services")

            for svc_name, svc_block in services.items():
                if not isinstance(svc_block, dict):
                    continue

                image = svc_block.get("image")
                version = svc_block.get("version")

                if not isinstance(image, str) or _is_blank(image):
                    continue
                if not isinstance(version, str) or _is_blank(version):
                    continue

                image = image.strip()
                version = version.strip()

                svc_doc = ensure_map(services_doc, str(svc_name))
                policy = _get_policy(svc_doc)

                if policy == "skip":
                    continue

                if policy == "force":
                    if svc_doc.get("image") != image:
                        svc_doc["image"] = image
                        changed = True
                    if svc_doc.get("version") != version:
                        svc_doc["version"] = version
                        changed = True
                    continue

                if _is_blank(svc_doc.get("image")):
                    svc_doc["image"] = image
                    changed = True
                if _is_blank(svc_doc.get("version")):
                    svc_doc["version"] = version
                    changed = True

    if not changed:
        return

    dump_document(host_vars_file, doc)
