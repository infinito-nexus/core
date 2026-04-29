from __future__ import annotations

from pathlib import Path

from utils.cache.yaml import load_yaml_any
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


def _ensure_ruamel_map(node: CommentedMap, key: str) -> CommentedMap:
    if key not in node or not isinstance(node.get(key), CommentedMap):
        node[key] = CommentedMap()
    return node[key]


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
    mirrors_images = mirrors_raw.get("images", {}) or {}
    has_applications = isinstance(mirrors_apps, dict) and bool(mirrors_apps)
    has_images = isinstance(mirrors_images, dict) and bool(mirrors_images)
    if not has_applications and not has_images:
        return  # no-op

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    if host_vars_file.exists():
        with host_vars_file.open("r", encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()

    if not isinstance(doc, CommentedMap):
        tmp = CommentedMap()
        for k, v in dict(doc).items():
            tmp[k] = v
        doc = tmp

    changed = False

    if has_applications:
        apps_doc = _ensure_ruamel_map(doc, "applications")
        for app_id, app_block in mirrors_apps.items():
            if not isinstance(app_block, dict):
                continue

            services = app_block.get("services") or {}
            if not isinstance(services, dict):
                continue

            app_doc = _ensure_ruamel_map(apps_doc, str(app_id))
            services_doc = _ensure_ruamel_map(app_doc, "services")

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

                svc_doc = _ensure_ruamel_map(services_doc, str(svc_name))
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

                # if_missing (default)
                if _is_blank(svc_doc.get("image")):
                    svc_doc["image"] = image
                    changed = True
                if _is_blank(svc_doc.get("version")):
                    svc_doc["version"] = version
                    changed = True

    if has_images:
        images_overrides_doc = _ensure_ruamel_map(doc, "images_overrides")
        for role_id, role_svcs in mirrors_images.items():
            if not isinstance(role_svcs, dict):
                continue

            role_images_doc = _ensure_ruamel_map(images_overrides_doc, str(role_id))
            for svc_name, svc_block in role_svcs.items():
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

                svc_images_doc = _ensure_ruamel_map(role_images_doc, str(svc_name))
                if _is_blank(svc_images_doc.get("image")):
                    svc_images_doc["image"] = image
                    changed = True
                if _is_blank(svc_images_doc.get("version")):
                    svc_images_doc["version"] = version
                    changed = True

    if not changed:
        return

    host_vars_file.parent.mkdir(parents=True, exist_ok=True)
    with host_vars_file.open("w", encoding="utf-8") as f:
        yaml_rt.dump(doc, f)
