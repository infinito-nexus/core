import unittest
from pathlib import Path

from utils.annotations.suppress import line_has_rule
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.host_agent import is_host_agent_service
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT


def service_errors(
    role_name: str, services: dict, exceptions: set, file_path: str
) -> list[str]:
    """Return the shared/enabled violations of one role's services.

    Args:
        role_name: the role the services belong to.
        services: the parsed meta/services.yml mapping.
        exceptions: service keys marked with a ``# nocheck: shared`` comment.
        file_path: the services file, for the messages.
    """
    errors = []
    for svc_name, svc_cfg in services.items():
        if not isinstance(svc_cfg, dict):
            continue

        enabled = svc_cfg.get("enabled")
        has_shared = "shared" in svc_cfg
        has_enabled = "enabled" in svc_cfg

        if (
            enabled is True
            and not has_shared
            and svc_name not in exceptions
            and not is_host_agent_service(svc_name)
        ):
            errors.append(
                f"{role_name}: services.{svc_name} has enabled=true "
                f"but is missing shared=true. "
                f"Add 'shared: true' or place a '# nocheck: shared' "
                f"comment on the line directly above '{svc_name}:' to mark "
                f"the intentional exception. ({file_path})"
            )

        if has_shared and not has_enabled:
            errors.append(
                f"{role_name}: services.{svc_name} declares 'shared' "
                f"but 'enabled' is not set. "
                f"Add 'enabled: true' or 'enabled: false'. ({file_path})"
            )
    return errors


class TestServiceSharedConsistency(unittest.TestCase):
    """
    For all roles in roles/*/meta/services.yml enforce two rules on every
    services.<name> entry:

    Rule 1, enabled requires shared:
      When a service has ``enabled: true`` it MUST also declare
      ``shared: true``.  If the requirement does not apply (e.g. the
      service is inherently role-local), mark the service key with a
      ``# nocheck: shared`` comment directly above it. Host-agent flags
      (``HOST_AGENT_SERVICES``, today ``wazuh``) are exempt: they mean
      "this host's agent collects the role's logs", not a shared service. Stacked comments
      are supported as long as no blank line
      breaks the comment block above the key. See
      ``docs/contributing/actions/testing/suppression.md``.

    Rule 2, shared requires enabled:
      When a service declares a ``shared`` key, it MUST also declare an
      ``enabled`` key (value may be ``true`` or ``false``).  A ``shared``
      key without a corresponding ``enabled`` key is ambiguous and
      therefore not allowed.
    """

    def _exception_services(self, file_path: str) -> set:
        """
        Scan the raw YAML text and return the set of service names whose
        key line is preceded by a contiguous comment block (no blank
        line in between) where any comment line carries the ``shared``
        suppression marker.
        """
        exceptions: set[str] = set()
        lines = read_text(file_path).splitlines()
        pending_exception = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                if line_has_rule(line, "shared"):
                    pending_exception = True
            elif not stripped:
                pending_exception = False
            else:
                if pending_exception and ":" in stripped:
                    key = stripped.split(":")[0].strip()
                    exceptions.add(key)
                pending_exception = False
        return exceptions

    def test_service_shared_consistency(self):
        roles_dir = PROJECT_ROOT / "roles"
        roles_prefix = str(roles_dir) + "/"
        files = sorted(
            p
            for p in iter_project_files(extensions=(".yml",))
            if p.startswith(roles_prefix) and p.endswith(f"/{ROLE_FILE_META_SERVICES}")
        )
        self.assertTrue(files, f"No meta/services.yml files found under {roles_dir}")

        errors = []

        for file_path in sorted(files):
            role_name = Path(file_path).parts[-3]
            try:
                cfg = load_yaml_any(file_path, default_if_missing={}) or {}
            except Exception as exc:
                errors.append(f"{role_name}: YAML parse error in {file_path}: {exc}")
                continue

            services = cfg if isinstance(cfg, dict) else {}
            errors.extend(
                service_errors(
                    role_name, services, self._exception_services(file_path), file_path
                )
            )

        if errors:
            self.fail(
                f"Service shared/enabled consistency violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


class TestHostAgentExemption(unittest.TestCase):
    def test_a_wazuh_opt_in_without_shared_passes(self):
        services = {"wazuh": {"enabled": True, "rule_block": 101000}}
        self.assertEqual(service_errors("web-app-pixelfed", services, set(), "x"), [])

    def test_another_service_without_shared_still_fails(self):
        services = {"matomo": {"enabled": True}}
        self.assertEqual(
            len(service_errors("web-app-pixelfed", services, set(), "x")), 1
        )

    def test_a_key_outside_the_list_cannot_use_the_exemption(self):
        services = {"wazuh-agent": {"enabled": True}}
        self.assertEqual(
            len(service_errors("web-app-pixelfed", services, set(), "x")), 1
        )

    def test_shared_without_enabled_still_fails_for_wazuh(self):
        services = {"wazuh": {"shared": True}}
        self.assertEqual(
            len(service_errors("web-app-pixelfed", services, set(), "x")), 1
        )


if __name__ == "__main__":
    unittest.main()
