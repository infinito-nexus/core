from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os


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
    if not os.path.isdir(roles_dir):
        raise ValueError(f"Roles directory '{roles_dir}' not found")

    # Per req-008, an "application role" is identified by the presence of
    # at least one of the project-owned `meta/<topic>.yml` files (services,
    # server, rbac, volumes, schema, users). This preserves the prior
    # assignment ordering: every role that previously had `meta/services.yml`
    # now has at least one of these files.
    application_marker_files = {
        "services.yml",
        "server.yml",
        "rbac.yml",
        "volumes.yml",
        "schema.yml",
        "users.yml",
    }
    discovered: set[str] = set()
    for entry in os.listdir(roles_dir):
        role_dir = os.path.join(roles_dir, entry)
        meta_dir = os.path.join(role_dir, "meta")
        if not os.path.isdir(meta_dir):
            continue
        for marker in application_marker_files:
            if os.path.isfile(os.path.join(meta_dir, marker)):
                discovered.add(entry)
                break
    sorted_ids = sorted(discovered)

    try:
        index = sorted_ids.index(application_id)
    except ValueError:
        raise ValueError(f"Application ID '{application_id}' not found in any role")

    return base_gid + index


# The Ansible LookupModule wrapper. We define it conditionally on
# ansible being importable: ansible's plugin loader only needs the class
# when an Ansible process actually loads this module via the lookup
# loader, and that always happens inside a process that has ansible
# installed (the playbook runner). Pure-Python importers (e.g.
# `utils.cache.applications._build_variants` running inside `cli.deploy.
# development init` on the GitHub Actions runner host) want
# `compute_application_gid` only and MUST NOT pay the ansible-import
# cost — see CI run 24935979190 for the regression that motivated this
# split.
try:
    from ansible.plugins.lookup import LookupBase
    from ansible.errors import AnsibleError

    class LookupModule(LookupBase):
        def run(self, terms, variables=None, **kwargs):
            application_id = terms[0]
            base_gid = kwargs.get("base_gid", 10000)
            roles_dir = kwargs.get("roles_dir", "roles")

            try:
                return [compute_application_gid(application_id, roles_dir, base_gid)]
            except ValueError as exc:
                raise AnsibleError(str(exc))

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
