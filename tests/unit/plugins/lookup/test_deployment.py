import unittest
from unittest.mock import patch

from plugins.lookup import deployment
from plugins.lookup.deployment import LookupModule


class TestDeploymentLookup(unittest.TestCase):
    def setUp(self):
        deployment._reset_cache_for_tests()

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_returns_dict_with_all_keys(self, mock_list):
        mock_list.return_value = ["web-app-friendica", "web-app-baserow"]
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": ["web-app-friendica"],
                "group_names": ["web-app-friendica", "web-app-baserow"],
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            set(result[0].keys()),
            {"whitelist", "running", "groups", "deployed", "runtime", "all"},
        )

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_running_falls_back_to_groups_when_whitelist_empty(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": [],
                "group_names": ["a", "b"],
            },
        )
        self.assertEqual(result[0]["running"], ["a", "b"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_running_uses_whitelist_when_non_empty(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": ["a"],
                "group_names": ["a", "b"],
            },
        )
        self.assertEqual(result[0]["running"], ["a"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_whitelist_reflects_raw_input(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": ["web-app-foo"],
                "group_names": ["web-app-bar"],
            },
        )
        # `whitelist` is the operator's raw input — no intersection with group.
        self.assertEqual(result[0]["whitelist"], ["web-app-foo"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_groups_reflects_raw_input(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": [],
                "group_names": ["a", "b", "c"],
            },
        )
        self.assertEqual(result[0]["groups"], ["a", "b", "c"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_all_reflects_invokable_apps(self, mock_list):
        mock_list.return_value = ["x", "y", "z"]
        result = LookupModule().run([], variables={"group_names": []})
        self.assertEqual(result[0]["all"], ["x", "y", "z"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_missing_vars_treated_as_empty(self, mock_list):
        mock_list.return_value = ["a"]
        result = LookupModule().run([], variables={})
        self.assertEqual(result[0]["whitelist"], [])
        self.assertEqual(result[0]["groups"], [])
        self.assertEqual(result[0]["running"], [])
        self.assertEqual(result[0]["all"], ["a"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_caches_same_input(self, mock_list):
        mock_list.return_value = ["a"]
        LookupModule().run(
            [], variables={"APPLICATIONS_WHITELIST": [], "group_names": ["a"]}
        )
        LookupModule().run(
            [], variables={"APPLICATIONS_WHITELIST": [], "group_names": ["a"]}
        )
        # invokable lookup runs only once for identical (whitelist, group)
        self.assertEqual(mock_list.call_count, 1)

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_whitelist_csv_string_tokenized(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": "web-app-foo,web-app-bar",
                "group_names": [],
            },
        )
        self.assertEqual(result[0]["whitelist"], ["web-app-foo", "web-app-bar"])
        self.assertEqual(result[0]["running"], ["web-app-foo", "web-app-bar"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_groups_csv_string_tokenized(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": [],
                "group_names": "a,b,c",
            },
        )
        self.assertEqual(result[0]["groups"], ["a", "b", "c"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_whitelist_csv_string_whitespace_trimmed(self, mock_list):
        mock_list.return_value = []
        result = LookupModule().run(
            [],
            variables={
                "APPLICATIONS_WHITELIST": " app1 , app2 ,, ",
                "group_names": [],
            },
        )
        self.assertEqual(result[0]["whitelist"], ["app1", "app2"])

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_deployed_uses_running_in_ephemeral_runtime(self, mock_list):
        mock_list.return_value = []
        for runtime in ("act", "github"):
            deployment._reset_cache_for_tests()
            result = LookupModule().run(
                [],
                variables={
                    "APPLICATIONS_WHITELIST": ["only-this"],
                    "group_names": ["only-this", "and-this", "and-that"],
                    "RUNTIME": runtime,
                },
            )
            self.assertEqual(result[0]["deployed"], ["only-this"])
            self.assertEqual(result[0]["runtime"], runtime)

    @patch("plugins.lookup.deployment.list_invokable_app_ids")
    def test_deployed_uses_groups_in_persistent_runtime(self, mock_list):
        mock_list.return_value = []
        for runtime in ("host", "dev", ""):
            deployment._reset_cache_for_tests()
            result = LookupModule().run(
                [],
                variables={
                    "APPLICATIONS_WHITELIST": ["partial"],
                    "group_names": ["partial", "still-running", "also-running"],
                    "RUNTIME": runtime,
                },
            )
            self.assertEqual(
                result[0]["deployed"],
                ["partial", "still-running", "also-running"],
            )


if __name__ == "__main__":
    unittest.main()
