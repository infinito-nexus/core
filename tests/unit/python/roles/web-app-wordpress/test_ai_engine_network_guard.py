"""The AI Engine network guard covers every site but the main site.

AI Engine 3.8.9 signs an MCP bearer-token request in as the first administrator
of the site and turns its MCP module on by default, so the guard has to answer
both the stored and the default ``mwai_options`` below the main site, and the
deploy has to read the stored row past the guard to clear it. No PHP runtime
runs here, so the shapes are read off the sources.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

_ROLE = PROJECT_ROOT / "roles/web-app-wordpress"
_GUARD = _ROLE / "files/mu-plugins/infinito-ai-engine-network.php"
_SWEEP = _ROLE / "files/php/ai_engine/network_mcp.php"
_TASK = _ROLE / "tasks/addons/ai-engine-stack-host.yml"


def _function_body(source: str, name: str) -> str:
    match = re.search(
        rf"function {name}\([^)]*\)\s*\{{(?P<body>.*?)\n\}}", source, re.DOTALL
    )
    if match is None:
        raise AssertionError(f"no function {name} in {_GUARD.name}")
    return match.group("body")


class TestAiEngineNetworkGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = read_text(str(_GUARD))

    def test_the_guard_answers_the_stored_and_the_default_options(self) -> None:
        for hook in ("option_mwai_options", "default_option_mwai_options"):
            with self.subTest(hook=hook):
                self.assertRegex(
                    self.guard,
                    rf"add_filter\('{hook}',\s*'infinito_ai_engine_network_options'",
                )

    def test_only_the_main_site_keeps_its_mcp_module_and_token(self) -> None:
        body = _function_body(self.guard, "infinito_ai_engine_network_options")
        guard_clause = re.search(
            r"if \((?P<cond>[^{]*)\)\s*\{\s*return \$options;", body
        )
        self.assertIsNotNone(guard_clause, "the options filter lost its early return")
        self.assertEqual(
            guard_clause.group("cond").strip(),
            "is_main_site() || !is_array($options)",
            "only the main site and a non-array value may leave the filter unchanged",
        )
        self.assertIn("$options['module_mcp'] = false;", body)
        self.assertIn("unset($options['mcp_bearer_token']);", body)

    def test_the_settings_stay_with_the_network_administrators(self) -> None:
        self.assertRegex(
            self.guard,
            r"add_filter\('mwai_allow_setup',\s*'infinito_ai_engine_network_allow_setup'",
        )
        body = _function_body(self.guard, "infinito_ai_engine_network_allow_setup")
        self.assertIn("return $allow && is_super_admin();", body)

    def test_the_guard_runs_on_every_multisite_network(self) -> None:
        self.assertRegex(self.guard, r"if \(!is_multisite\(\)\) \{\s*return;\s*\}")

    def test_the_deploy_reads_the_stored_row_past_the_guard_below_the_main_site(
        self,
    ) -> None:
        sweep = read_text(str(_SWEEP))
        self.assertLess(
            sweep.index("remove_all_filters('option_mwai_options');"),
            sweep.index("get_option('mwai_options')"),
        )
        self.assertRegex(sweep, r"if \(is_main_site\(\$blog_id\)\) \{\s*continue;")
        task = read_text(str(_TASK))
        self.assertIn("php/ai_engine/network_mcp.php", task)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
