import functools
import os
from pathlib import Path

_APPLICATION_MARKER_FILES = (
    "services.yml",
    "server.yml",
    "rbac.yml",
    "volumes.yml",
    "schema.yml",
    "users.yml",
)


@functools.cache
def _discover_sorted_application_ids(roles_dir_key: str) -> tuple[str, ...]:
    discovered: set[str] = set()
    for entry in os.listdir(roles_dir_key):
        meta_dir = Path(roles_dir_key, entry, "meta")
        if not meta_dir.is_dir():
            continue
        if any((meta_dir / marker).is_file() for marker in _APPLICATION_MARKER_FILES):
            discovered.add(entry)
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

    An "application role" carries at least one project-owned
    `meta/<topic>.yml` marker file (services, server, rbac, volumes,
    schema, users).

    Raises ``ValueError`` (not ``AnsibleError``) for portability.
    """
    if not Path(roles_dir).is_dir():
        raise ValueError(f"Roles directory '{roles_dir}' not found")

    sorted_ids = _discover_sorted_application_ids(str(Path(roles_dir).resolve()))

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
