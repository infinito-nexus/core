import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

ROOT = "/opt/compose/"
LAYOUT = (".env", "config", "services", "volumes")
KNOWN = [
    f"web-app-{name}"
    for name in (
        "mailu",
        "stalwart",
        "baserow",
        "discourse",
        "handmade",
        "partial",
        "odd",
        "dotenv",
        "outer",
        "inner",
        "alpha",
        "zeta",
    )
] + ["svc-db-postgres", "svc-db-mariadb", "svc-prx-openresty", "web-svc-simpleicons"]


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-svc-compose"
        / "filter_plugins"
        / "compose_decommission_plan.py"
    )
    spec = importlib.util.spec_from_file_location("compose_decommission_plan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _entry(path, isdir=False, isreg=False):
    return {"path": path, "isdir": isdir, "isreg": isreg, "islnk": False}


def _instance(name, skip=()):
    base = f"/opt/compose/{name}"
    entries = [_entry(base, isdir=True)]
    entries += [_entry(f"{base}/{d}", isdir=True) for d in LAYOUT if d not in skip]
    if "compose.yml" not in skip:
        entries.append(_entry(f"{base}/compose.yml", isreg=True))
    return entries


def _namesakes(instance, *lines):
    return {
        "ansible_loop_var": "compose_stale_candidate",
        "compose_stale_candidate": instance,
        "stdout_lines": list(lines),
    }


class TestComposeDecommissionPlan(unittest.TestCase):
    def setUp(self):
        self.plan = _load_module().compose_decommission_plan

    def test_the_instance_of_a_role_removed_from_the_host_is_stale(self):
        entries = _instance("mailu") + _instance("stalwart")
        self.assertEqual(
            self.plan(entries, ROOT, ["web-app-stalwart"], KNOWN),
            {"stale": ["/opt/compose/mailu"], "unmanaged": []},
        )

    def test_the_instances_of_active_shared_services_are_kept(self):
        entries = (
            _instance("postgres")
            + _instance("mariadb")
            + _instance("openresty")
            + _instance("simpleicons")
        )
        active = [
            "svc-db-postgres",
            "svc-db-mariadb",
            "svc-prx-openresty",
            "web-svc-simpleicons",
        ]
        self.assertEqual(
            self.plan(entries, ROOT, active, KNOWN), {"stale": [], "unmanaged": []}
        )

    def test_a_full_instance_of_no_known_role_is_unmanaged(self):
        entries = _instance("nextcloud-old") + _instance("mailu.bak")
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN),
            {
                "stale": [],
                "unmanaged": ["/opt/compose/mailu.bak", "/opt/compose/nextcloud-old"],
            },
        )

    def test_a_directory_without_compose_file_is_unmanaged(self):
        entries = _instance("handmade", skip=("compose.yml",))
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN),
            {"stale": [], "unmanaged": ["/opt/compose/handmade"]},
        )

    def test_each_missing_layout_directory_makes_the_directory_unmanaged(self):
        for missing in LAYOUT:
            with self.subTest(missing=missing):
                self.assertEqual(
                    self.plan(_instance("partial", skip=(missing,)), ROOT, [], KNOWN),
                    {"stale": [], "unmanaged": ["/opt/compose/partial"]},
                )

    def test_a_compose_file_that_is_a_directory_does_not_count(self):
        entries = [
            *_instance("odd", skip=("compose.yml",)),
            _entry("/opt/compose/odd/compose.yml", isdir=True),
        ]
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN),
            {"stale": [], "unmanaged": ["/opt/compose/odd"]},
        )

    def test_a_layout_entry_that_is_a_file_does_not_count(self):
        entries = [
            *_instance("dotenv", skip=(".env",)),
            _entry("/opt/compose/dotenv/.env", isreg=True),
        ]
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN),
            {"stale": [], "unmanaged": ["/opt/compose/dotenv"]},
        )

    def test_hidden_directories_are_ignored(self):
        self.assertEqual(
            self.plan(_instance(".trash"), ROOT, [], KNOWN),
            {"stale": [], "unmanaged": []},
        )

    def test_symlinks_and_files_below_the_root_are_ignored(self):
        entries = [
            {
                "path": "/opt/compose/linked",
                "isdir": False,
                "isreg": False,
                "islnk": True,
            },
            _entry("/opt/compose/README", isreg=True),
        ]
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN), {"stale": [], "unmanaged": []}
        )

    def test_a_layout_found_deeper_does_not_make_an_instance(self):
        entries = [_entry("/opt/compose/outer", isdir=True)] + [
            dict(
                entry,
                path=entry["path"].replace("/opt/compose/", "/opt/compose/outer/"),
            )
            for entry in _instance("inner")[1:]
        ]
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN),
            {"stale": [], "unmanaged": ["/opt/compose/outer"]},
        )

    def test_the_root_matches_with_and_without_trailing_slash(self):
        for root in ("/opt/compose", "/opt/compose/"):
            with self.subTest(root=root):
                self.assertEqual(
                    self.plan(_instance("mailu"), root, [], KNOWN)["stale"],
                    ["/opt/compose/mailu"],
                )

    def test_a_group_name_that_is_no_role_does_not_keep_a_stale_instance(self):
        self.assertEqual(
            self.plan(_instance("mailu"), ROOT, ["servers", "web-app-stalwart"], KNOWN)[
                "stale"
            ],
            ["/opt/compose/mailu"],
        )

    def test_both_lists_come_back_sorted(self):
        entries = (
            _instance("mailu")
            + _instance("baserow")
            + _instance("zeta", skip=("compose.yml",))
            + _instance("alpha", skip=("compose.yml",))
        )
        self.assertEqual(
            self.plan(entries, ROOT, [], KNOWN),
            {
                "stale": ["/opt/compose/baserow", "/opt/compose/mailu"],
                "unmanaged": ["/opt/compose/alpha", "/opt/compose/zeta"],
            },
        )

    def test_no_entries_yield_an_empty_plan(self):
        self.assertEqual(
            self.plan([], ROOT, ["web-app-stalwart"], KNOWN),
            {"stale": [], "unmanaged": []},
        )

    def test_wrongly_typed_arguments_fail(self):
        cases = (
            ("/opt/compose/mailu", ROOT, [], KNOWN),
            ([], ["/opt/compose/"], [], KNOWN),
            ([], ROOT, "web-app-mailu", KNOWN),
            ([], ROOT, [], "web-app-mailu"),
        )
        for args in cases:
            with self.subTest(args=args), self.assertRaises(AnsibleFilterError):
                self.plan(*args)


class TestComposeDecommissionConfirm(unittest.TestCase):
    def setUp(self):
        self.confirm = _load_module().compose_decommission_confirm
        self.plan = {
            "stale": ["/opt/compose/discourse", "/opt/compose/mailu"],
            "unmanaged": ["/opt/compose/handmade"],
        }

    def test_instances_without_namesakes_stay_stale(self):
        self.assertEqual(
            self.confirm(
                self.plan,
                [
                    _namesakes("/opt/compose/discourse"),
                    _namesakes("/opt/compose/mailu"),
                ],
            ),
            dict(self.plan, foreign=[]),
        )

    def test_a_namesake_of_the_own_project_keeps_the_instance_stale(self):
        result = self.confirm(
            self.plan,
            [
                _namesakes("/opt/compose/discourse"),
                _namesakes("/opt/compose/mailu", "mailu mailu"),
            ],
        )
        self.assertEqual(
            result["stale"], ["/opt/compose/discourse", "/opt/compose/mailu"]
        )

    def test_a_namesake_without_compose_project_holds_the_instance_back(self):
        self.assertEqual(
            self.confirm(
                self.plan,
                [
                    _namesakes("/opt/compose/discourse", "discourse "),
                    _namesakes("/opt/compose/mailu"),
                ],
            ),
            {
                "stale": ["/opt/compose/mailu"],
                "unmanaged": ["/opt/compose/handmade"],
                "foreign": ["/opt/compose/discourse"],
            },
        )

    def test_a_namesake_of_another_project_holds_the_instance_back(self):
        result = self.confirm(
            self.plan,
            [
                _namesakes("/opt/compose/discourse"),
                _namesakes("/opt/compose/mailu", "mailu mailu", "mailu stalwart"),
            ],
        )
        self.assertEqual(result["foreign"], ["/opt/compose/mailu"])
        self.assertEqual(result["stale"], ["/opt/compose/discourse"])

    def test_no_probe_results_change_nothing(self):
        plan = {"stale": [], "unmanaged": []}
        self.assertEqual(self.confirm(plan, []), dict(plan, foreign=[]))

    def test_wrongly_typed_arguments_fail(self):
        for args in (([], []), (self.plan, {})):
            with self.subTest(args=args), self.assertRaises(AnsibleFilterError):
                self.confirm(*args)


if __name__ == "__main__":
    unittest.main()
