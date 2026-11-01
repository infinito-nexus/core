import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "web-app-weblate" / "files" / "python" / "settings_override.py"
ASSOCIATE_BY_EMAIL = "social_core.pipeline.social_auth.associate_by_email"
UPSTREAM_SOURCE = "https://github.com/WeblateOrg/weblate/blob/weblate-2026.9/weblate/settings_docker.py#L639-L664"
UPSTREAM_PIPELINE = [
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "weblate.accounts.pipeline.store_params",
    "weblate.accounts.pipeline.verify_open",
    "social_core.pipeline.user.get_username",
    "weblate.accounts.pipeline.require_email",
    "social_core.pipeline.mail.mail_validation",
    "weblate.accounts.pipeline.revoke_mail_code",
    "weblate.accounts.pipeline.ensure_valid",
    "weblate.accounts.pipeline.remove_account",
    ASSOCIATE_BY_EMAIL,
    "weblate.accounts.pipeline.reauthenticate",
    "weblate.accounts.pipeline.verify_username",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "weblate.accounts.pipeline.handle_invite",
    "social_core.pipeline.social_auth.load_extra_data",
    "weblate.accounts.pipeline.second_factor",
    "weblate.accounts.pipeline.user_full_name",
    "weblate.accounts.pipeline.store_email",
    "weblate.accounts.pipeline.notify_connect",
    "weblate.accounts.pipeline.password_reset",
]


def run_override(pipeline):
    namespace = {"__name__": "weblate.settings_docker", "SOCIAL_AUTH_PIPELINE": list(pipeline)}
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), namespace)
    return namespace


class SettingsOverrideTests(unittest.TestCase):
    def test_associate_by_email_leaves_the_pipeline(self):
        self.assertNotIn(ASSOCIATE_BY_EMAIL, run_override(UPSTREAM_PIPELINE)["SOCIAL_AUTH_PIPELINE"])

    def test_every_other_step_keeps_its_upstream_order(self):
        self.assertEqual(
            run_override(UPSTREAM_PIPELINE)["SOCIAL_AUTH_PIPELINE"],
            [step for step in UPSTREAM_PIPELINE if step != ASSOCIATE_BY_EMAIL],
            UPSTREAM_SOURCE,
        )

    def test_a_step_upstream_inserted_before_the_override_survives(self):
        pipeline = list(UPSTREAM_PIPELINE)
        pipeline.insert(pipeline.index("weblate.accounts.pipeline.second_factor") + 1, "weblate.legal.pipeline.tos_confirm")
        result = run_override(pipeline)["SOCIAL_AUTH_PIPELINE"]
        self.assertIn("weblate.legal.pipeline.tos_confirm", result)
        self.assertEqual(result, [step for step in pipeline if step != ASSOCIATE_BY_EMAIL])

    def test_the_subject_lookup_still_precedes_account_creation(self):
        result = run_override(UPSTREAM_PIPELINE)["SOCIAL_AUTH_PIPELINE"]
        self.assertLess(
            result.index("social_core.pipeline.social_auth.social_user"),
            result.index("social_core.pipeline.user.create_user"),
        )

    def test_it_defines_no_other_setting(self):
        namespace = run_override(UPSTREAM_PIPELINE)
        self.assertEqual(
            {name for name in namespace if name.isupper()}, {"SOCIAL_AUTH_PIPELINE"}
        )


if __name__ == "__main__":
    unittest.main()
