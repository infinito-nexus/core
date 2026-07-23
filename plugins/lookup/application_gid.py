import os
from functools import cache
from pathlib import Path

_APPLICATION_MARKER_FILES = (
    "services.yml",
    "server.yml",
    "rbac.yml",
    "volumes.yml",
    "schema.yml",
    "users.yml",
)


@cache
def _discover_application_ids(roles_dir_abs: str) -> tuple[str, ...]:
    """Sorted application role ids under *roles_dir_abs*, memoised per
    process (utils.cache philosophy: CLI/test invocations rescan at most
    once; a role added mid-process needs a fresh interpreter or
    ``_discover_application_ids.cache_clear()``).

    An "application role" is identified by the presence of at least one
    project-owned ``meta/<topic>.yml`` marker file.
    """
    discovered: list[str] = []
    with os.scandir(roles_dir_abs) as entries:
        for entry in entries:
            if not entry.is_dir():
                continue
            meta_dir = Path(entry.path) / "meta"
            for marker in _APPLICATION_MARKER_FILES:
                if (meta_dir / marker).is_file():
                    discovered.append(entry.name)
                    break
    return tuple(sorted(discovered))


def compute_application_gid(application_id, roles_dir="roles", base_gid=10000):
    """Pure-Python GID resolver — no ansible dependency.

    Sorts every `<roles_dir>/<role>/meta/services.yml`-bearing role
    alphabetically by `<role>` and returns ``base_gid + index`` for the
    requested ``application_id``. Extracted so callers that only need
    the GID computation (e.g. ``utils.cache.applications._build_variants`` on
    the GitHub Actions runner host, where the runner Python ships
    without ``ansible``) can import THIS function instead of the
    ``LookupModule`` class — that one transitively pulls
    ``ansible.plugins.lookup.LookupBase`` and raises
    ``ModuleNotFoundError`` on ansible-less hosts.

    Raises ``ValueError`` (not ``AnsibleError``) for portability.
    """
    if not Path(roles_dir).is_dir():
        raise ValueError(f"Roles directory '{roles_dir}' not found")

    sorted_ids = _discover_application_ids(str(Path(roles_dir).resolve()))

    try:
        index = sorted_ids.index(application_id)
    except ValueError:
        raise ValueError(
            f"Application ID '{application_id}' not found in any role"
        ) from None

    return base_gid + index


try:
    from ansible.errors import AnsibleError
    from ansible.plugins.lookup import LookupBase

    class LookupModule(LookupBase):
        def run(self, terms, variables=None, **kwargs):
            application_id = terms[0]
            base_gid = kwargs.get("base_gid", 10000)
            roles_dir = kwargs.get("roles_dir", "roles")

            try:
                return [compute_application_gid(application_id, roles_dir, base_gid)]
            except ValueError as exc:
                raise AnsibleError(str(exc)) from exc

except ImportError:  # pragma: no cover - exercised on ansible-less hosts only
    # Sentinel so callers that *try* to instantiate the lookup outside
    # an Ansible process get a clear, actionable error instead of a
    # confusing AttributeError or NameError.
    class LookupModule:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "plugins.lookup.application_gid.LookupModule requires "
                "ansible at runtime. Use compute_application_gid() "
                "directly for ansible-less code paths."
            )
