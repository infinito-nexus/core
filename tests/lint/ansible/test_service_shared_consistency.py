import unittest
import glob
import yaml
from pathlib import Path


class TestServiceSharedConsistency(unittest.TestCase):
    """
    For all roles in roles/*/meta/services.yml enforce two rules on every
    services.<name> entry:

    Rule 1 — enabled requires shared:
      When a service has ``enabled: true`` it MUST also declare
      ``shared: true``.  If the requirement does not apply (e.g. the
      service is inherently role-local), mark the service key with a
      ``# noqa: shared`` comment on the line directly above it to
      register the intentional exception.

    Rule 2 — shared requires enabled:
      When a service declares a ``shared`` key, it MUST also declare an
      ``enabled`` key (value may be ``true`` or ``false``).  A ``shared``
      key without a corresponding ``enabled`` key is ambiguous and
      therefore not allowed.
    """

    EXCEPTION_MARKER = "noqa: shared"

    def _exception_services(self, file_path: str) -> set:
        """
        Scan the raw YAML text and return the set of service names whose
        key line is preceded directly (no blank line in between) by a
        comment that contains EXCEPTION_MARKER.
        """
        exceptions = set()
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        pending_exception = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                if self.EXCEPTION_MARKER in stripped:
                    pending_exception = True
                # Non-matching comment does not reset pending state so that
                # stacked comments still work.
            elif not stripped:
                # Blank line breaks the association between comment and key.
                pending_exception = False
            else:
                if pending_exception and ":" in stripped:
                    key = stripped.split(":")[0].strip()
                    exceptions.add(key)
                pending_exception = False
        return exceptions

    def test_service_shared_consistency(self):
        roles_dir = Path(__file__).resolve().parent.parent.parent.parent / "roles"
        pattern = str(roles_dir / "*" / "meta" / "services.yml")
        files = glob.glob(pattern)
        self.assertTrue(
            files, f"No config/main.yml files found with pattern: {pattern}"
        )

        errors = []

        for file_path in sorted(files):
            role_name = Path(file_path).parts[-3]
            try:
                cfg = yaml.safe_load(Path(file_path).read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                errors.append(f"{role_name}: YAML parse error in {file_path}: {exc}")
                continue

            # Per req-008 the file root of meta/services.yml IS the
            # services map (no `compose.services` wrapper).
            services = cfg if isinstance(cfg, dict) else {}

            exceptions = self._exception_services(file_path)

            for svc_name, svc_cfg in services.items():
                if not isinstance(svc_cfg, dict):
                    continue

                enabled = svc_cfg.get("enabled")
                has_shared = "shared" in svc_cfg
                has_enabled = "enabled" in svc_cfg

                # Rule 1: enabled=true requires shared=true
                if enabled is True and not has_shared:
                    if svc_name not in exceptions:
                        errors.append(
                            f"{role_name}: services.{svc_name} has enabled=true "
                            f"but is missing shared=true. "
                            f"Add 'shared: true' or place a '# {self.EXCEPTION_MARKER}' "
                            f"comment on the line directly above '{svc_name}:' to mark "
                            f"the intentional exception. ({file_path})"
                        )

                # Rule 2: shared key requires enabled key
                if has_shared and not has_enabled:
                    errors.append(
                        f"{role_name}: services.{svc_name} declares 'shared' "
                        f"but 'enabled' is not set. "
                        f"Add 'enabled: true' or 'enabled: false'. ({file_path})"
                    )

        if errors:
            self.fail(
                f"Service shared/enabled consistency violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


if __name__ == "__main__":
    unittest.main()
