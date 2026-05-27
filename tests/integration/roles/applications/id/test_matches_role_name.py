import unittest
import warnings
from pathlib import Path

# import your filters
from plugins.filter.invokable_paths import get_invokable_paths, get_non_invokable_paths
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


class TestApplicationIdAndInvocability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.roles_dir = str(PROJECT_ROOT / "roles")

        # get lists of invokable and non-invokable role *names*
        # filters return dash-joined paths; for top-level roles names are just the basename
        cls.invokable = {p.split("-", 1)[0] for p in get_invokable_paths()}
        cls.non_invokable = {p.split("-", 1)[0] for p in get_non_invokable_paths()}

    def test_application_id_presence_and_match(self):
        """
        - Invokable roles must have application_id defined (else fail).
        - Non-invokable roles must NOT have application_id (else fail).
        - If application_id exists but != folder name, warn and recommend aligning.
        """
        for role_path in Path(self.roles_dir).iterdir():
            if not role_path.is_dir():
                continue

            role_name = role_path.name
            vars_main = role_path / ROLE_FILE_VARS_MAIN

            # load vars/main.yml if it exists
            data = {}
            if vars_main.exists():
                data = load_yaml_any(str(vars_main)) or {}

            app_id = data.get("application_id")

            if role_name in self.invokable:
                # must have application_id
                if app_id is None:
                    self.fail(
                        f"{role_name}: invokable role is missing 'application_id' in vars/main.yml"
                    )
            elif role_name in self.non_invokable:
                # must NOT have application_id
                if app_id is not None:
                    self.fail(
                        f"{role_name}: non-invokable role should not define 'application_id' in vars/main.yml"
                    )
            else:
                # roles not mentioned in categories.yml? we'll skip them
                continue

            # if present but mismatched, warn
            if app_id is not None and app_id != role_name:
                warnings.warn(
                    f"{role_name}: 'application_id' is '{app_id}',"
                    f" but the folder name is '{role_name}'."
                    " Consider setting application_id to exactly the role folder name to avoid confusion.",
                    stacklevel=2,
                )

        # if we get here, all presence/absence checks passed
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
