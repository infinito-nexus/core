"""
Jinja filter: `inj_features(kind)` filters a list of features to only those
that actually provide the corresponding snippet template file.

- kind='head' -> roles/sys-front-inj-<feature>/templates/head_sub.j2
- kind='body' -> roles/sys-front-inj-<feature>/templates/body_sub.j2

If the feature's role directory (roles/sys-front-inj-<feature>) does not
exist, this filter raises FileNotFoundError.

Usage in a template:
    {% set head_features = SRV_WEB_INJ_COMP_FEATURES_ALL | inj_features('head') %}
    {% set body_features = SRV_WEB_INJ_COMP_FEATURES_ALL | inj_features('body') %}
"""

from pathlib import Path

# Role-bundled plugin: Ansible loads this file by file path with no
# package context, so `from . import PROJECT_ROOT` cannot resolve here.
# nocheck: project-root-import
_ROLES_DIR = str(Path(__file__).resolve().parents[2])


def _feature_role_dir(feature: str) -> str:
    return str(Path(_ROLES_DIR) / f"sys-front-inj-{feature}")


def _has_snippet(feature: str, kind: str) -> bool:
    if kind not in ("head", "body"):
        raise ValueError("kind must be 'head' or 'body'")

    role_dir = _feature_role_dir(feature)
    if not Path(role_dir).is_dir():
        raise FileNotFoundError(
            f"[inj_snippets] Expected role directory not found for feature "
            f"'{feature}': {role_dir}"
        )

    path = str(Path(role_dir) / "templates" / f"{kind}_sub.j2")
    return Path(path).exists()


def inj_features_filter(features, kind: str = "head"):
    if not isinstance(features, (list, tuple)):
        return []
    # Validation + filtering in one pass; will raise if a role dir is missing.
    valid = []
    for f in features:
        name = str(f)
        if _has_snippet(name, kind):
            valid.append(name)
    return valid


class FilterModule:
    def filters(self):
        return {
            "inj_features": inj_features_filter,
        }
