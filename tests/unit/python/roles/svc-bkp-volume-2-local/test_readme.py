import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

README = PROJECT_ROOT / "roles" / "svc-bkp-volume-2-local" / "README.md"
PATHS = PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml"


def section(text, heading):
    """
    Args:
        text: the README.
        heading: an H2 heading without its hashes.

    Returns:
        The section's body up to the next H2, empty when it is missing.
    """
    pattern = rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    return match.group(1) if match else ""


def missing_restore_credentials(text):
    """
    Args:
        text: the README.

    Returns:
        The restore facts the backup set section does not name.
    """
    body = section(text, "Backup set")
    wanted = (
        "`access_key_encryption`",
        "`web-app-semaphore`",
        "`seal_key`",
        "`web-app-openbao`",
        "Semaphore and Keycloak databases",
        "OpenBao, SeaweedFS and Gitea",
    )
    return [token for token in wanted if token not in body]


def missing_signal_facts(text):
    """
    Args:
        text: the README.

    Returns:
        The facts of the maintenance signal and of the restore order the
        README does not name.
    """
    signal = section(text, "Maintenance signal")
    recover = section(text, "Recover")
    directory = load_yaml_any(str(PATHS))["DIR_MAINTENANCE"]
    wanted = {
        "path": f"`{directory}/backup.json`" in signal,
        "applications": "`applications`" in signal,
        "started": "`started`" in signal,
        "until": "`until`" in signal,
        "offset": "numeric offset" in signal,
        "atomic rename": "atomic rename" in signal,
        "failed run": "`ExecStopPost`" in signal,
        "snapshot run": "snapshot run" in signal.lower(),
        "reboot": "reboot" in signal,
        "stale": "past its `until`" in signal,
        "consumer flag": "`services.maintenance.enabled`" in signal,
        "read-only": "read-only" in signal,
        "no vhost": "no vhost" in signal,
        "workspace apply": "`workspace apply`" in recover,
    }
    return [fact for fact, present in wanted.items() if not present]


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(README))

    def test_the_readme_names_the_restore_credentials(self):
        self.assertEqual(missing_restore_credentials(self.text), [])

    def test_negative_control_a_readme_without_the_seal_key_fails(self):
        stripped = self.text.replace("`seal_key`", "the key")
        self.assertIn("`seal_key`", missing_restore_credentials(stripped))

    def test_the_readme_names_the_maintenance_signal(self):
        self.assertEqual(missing_signal_facts(self.text), [])

    def test_negative_control_a_readme_without_the_signal_section_fails(self):
        stripped = self.text.replace("## Maintenance signal", "## Signal")
        self.assertIn("path", missing_signal_facts(stripped))


if __name__ == "__main__":
    unittest.main()
