import unittest

from jinja2 import Environment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

RESOLVE_SITE = (
    PROJECT_ROOT / "roles" / "sys-front-inj-matomo" / "tasks" / "resolve_site.yml"
)
INSTALL_PATH = (
    PROJECT_ROOT / "roles" / "web-app-matomo" / "tasks" / "03_install_path.yml"
)

SCOPE = "abc"
SITES = [{"idsite": "3", "main_url": "https://a.example"}]


def _tasks(path):
    return load_yaml_any(str(path)) or []


def _guard(task):
    when = task["when"]
    return when if isinstance(when, list) else [when]


def _eval(expressions, context) -> bool:
    env = Environment(autoescape=True)
    return all(bool(env.compile_expression(expr)(**context)) for expr in expressions)


def _task(tasks, predicate):
    return next(task for task in tasks if predicate(task))


class TestNegativeSiteCache(unittest.TestCase):
    def setUp(self):
        tasks = _tasks(RESOLVE_SITE)
        self.load = _task(tasks, lambda t: t.get("register") == "matomo_site_list")
        self.site_check = _task(tasks, lambda t: t.get("register") == "site_check")
        self.cached_id = _task(
            tasks,
            lambda t: "matomo_cached_site_ids" in str(t.get("vars", {})),
        )

    def _state(self, sites, scope=SCOPE):
        return {
            "matomo_site_cache": {"scope": scope, "sites": sites},
            "matomo_site_cache_scope": SCOPE,
            "matomo_site_id": "",
            "matomo_effective_token": "token",
        }

    def test_a_cached_absence_skips_both_api_calls(self):
        state = self._state(None)
        self.assertFalse(_eval(_guard(self.load), state))
        self.assertFalse(_eval(_guard(self.site_check), state))
        self.assertFalse(_eval(_guard(self.cached_id), state))

    def test_a_cached_list_still_asks_for_an_unknown_site(self):
        self.assertTrue(_eval(_guard(self.site_check), self._state(SITES)))

    def test_a_cache_of_another_scope_reloads_the_list(self):
        self.assertTrue(_eval(_guard(self.load), self._state(None, scope="")))


class TestMatomoDropsTheCacheBeforeReinjecting(unittest.TestCase):
    def test_the_reset_precedes_the_consumer_reinjection(self):
        tasks = _tasks(INSTALL_PATH)
        names = [str(t.get("include_tasks", "")) for t in tasks]
        reinject = names.index("08_reinject_consumers.yml")
        reset = _task(
            tasks[:reinject],
            lambda t: "matomo_site_cache" in t.get("ansible.builtin.set_fact", {}),
        )
        self.assertEqual(
            reset["ansible.builtin.set_fact"]["matomo_site_cache"]["scope"], ""
        )


if __name__ == "__main__":
    unittest.main()
