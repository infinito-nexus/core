import unittest
from unittest import mock

from utils.preflight.context import deploy_closure_context

MODULE = "utils.preflight.context"


class TestDeployClosureContext(unittest.TestCase):
    def _build(self, closure=None, side_effect=None):
        plugins = {
            "applications": mock.Mock(),
            "config": mock.Mock(),
            "domains": mock.Mock(),
        }
        plugins["applications"].run.return_value = [{"web-app-matomo": {}}]
        plugins["config"].run.side_effect = lambda terms, variables=None: [
            f"{terms[0]}:{terms[1]}"
        ]
        plugins["domains"].run.return_value = [["matomo.example.org"]]
        lookup = mock.Mock(_loader="loader", _templar=None)
        with (
            mock.patch(
                f"{MODULE}.lookup_loader.get",
                side_effect=lambda name, **kwargs: plugins[name],
            ),
            mock.patch(f"{MODULE}.types_from_group_names", return_value=["server"]),
            mock.patch(
                f"{MODULE}.deploy_closure",
                return_value=closure or {"web-app-matomo", "svc-db-mariadb"},
                side_effect=side_effect,
            ) as closure_mock,
        ):
            context = deploy_closure_context(
                lookup, {"group_names": ["web-app-matomo"]}, ["web-app-matomo"]
            )
            readers = (
                context.config("web-app-matomo", "services.matomo.name", ""),
                context.lookup("domains", "web-app-matomo", []),
            )
        return context, readers, closure_mock

    def test_the_closure_roles_come_sorted(self):
        context, _readers, _closure = self._build()
        self.assertEqual(context.roles, ["svc-db-mariadb", "web-app-matomo"])
        self.assertEqual(context.applications, {"web-app-matomo": {}})

    def test_the_host_groups_seed_the_closure(self):
        _context, _readers, closure = self._build()
        self.assertEqual(closure.call_args.args[1], ["web-app-matomo"])
        self.assertEqual(closure.call_args.kwargs["host_types"], ["server"])

    def test_the_readers_forward_to_their_lookups(self):
        _context, readers, _closure = self._build()
        self.assertEqual(
            readers, ("web-app-matomo:services.matomo.name", ["matomo.example.org"])
        )

    def test_a_closure_error_propagates(self):
        with self.assertRaises(ValueError):
            self._build(side_effect=ValueError("broken"))


if __name__ == "__main__":
    unittest.main()
