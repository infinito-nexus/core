from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.tests.buckets import buckets, register

from .test_resolve_render_once import (
    DESIGN_DIR,
    DOMAIN,
    ONION,
    resolve_tasks,
    run_tasks,
)

COSMOS = "web-app-cst-cosmos"
ROLE_SHEETS = ("templates/style.css.j2", "files/style.css", "files/logo.css")
COSMOS_SHEET = "templates/cosmos.css.j2"
COMPOSE = Path("templates") / "css" / "app.css.j2"
COSMOS_LINE = "{{ app_cosmos_css }}\n"
PRE_COSMOS_COMPOSE = Path("pre-cosmos") / "app.css.j2"
PRE_COSMOS_STYLE = (
    "{{ (lookup('template_shallow', _app_compose_src, "
    "template_vars={'app_body_css': app_body_css, 'app_logo_css': app_logo_css}) "
    "| trim | replace(_cdn_origin, '/')) "
    "if (app_body_css ~ app_logo_css) | length > 0 else '' }}"
)
PRE_COSMOS_PRESENT = "{{ (app_body_css ~ app_logo_css) | length > 0 }}"
VHOSTS = (f"x.app.{DOMAIN}", f"x.app.{ONION}")


def roles() -> list[str]:
    """
    Returns:
        Every role, the custom roles a pull places included.
    """
    return sorted(
        path.name for path in (PROJECT_ROOT / "roles").iterdir() if path.is_dir()
    )


def fixture(root: Path) -> None:
    """
    Args:
        root: the empty playbook directory to fill. Every role gets its own
            sheets as literal text, the cosmos sheet as its template, and
            ``sys-front-inj-design`` its templates beside the pre-cosmos
            ``app.css.j2``.
    """
    for role in roles():
        source, target = PROJECT_ROOT / "roles" / role, root / "roles" / role
        target.mkdir(parents=True)
        for name in ROLE_SHEETS:
            if (source / name).is_file():
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                (target / name).write_text(
                    "{% raw %}" + read_text(str(source / name)) + "{% endraw %}",
                    encoding="utf-8",
                )
        if (source / COSMOS_SHEET).is_file():
            (target / COSMOS_SHEET).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / COSMOS_SHEET, target / COSMOS_SHEET)
    design = root / "roles" / DESIGN_DIR.name
    shutil.rmtree(design)
    shutil.copytree(DESIGN_DIR / "templates", design / "templates")
    compose = read_text(str(DESIGN_DIR / COMPOSE))
    if compose.count(COSMOS_LINE) != 1:
        raise AssertionError(f"{COMPOSE} must append the cosmos sheet exactly once")
    (root / PRE_COSMOS_COMPOSE).parent.mkdir(parents=True)
    (root / PRE_COSMOS_COMPOSE).write_text(
        compose.replace(COSMOS_LINE, ""), encoding="utf-8"
    )


def pre_cosmos_task(root: Path) -> dict:
    """
    Args:
        root: the playbook directory :func:`fixture` filled.

    Returns:
        The style resolve task with the expressions it had before cosmos.
    """
    task = resolve_tasks()[0]
    task_vars = {
        key: value
        for key, value in task["vars"].items()
        if key not in ("_app_cosmos_src", "app_cosmos_css")
    }
    return {
        **task,
        "vars": {
            **task_vars,
            "_app_compose_src": str(root / PRE_COSMOS_COMPOSE),
            "_app_style_css": PRE_COSMOS_STYLE,
        },
        "set_fact": {**task["set_fact"], "app_style_present": PRE_COSMOS_PRESENT},
    }


def version(facts: dict) -> str:
    return hashlib.sha1(
        facts["app_style_css"].encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def ships(root: Path, app: str, names: tuple[str, ...]) -> bool:
    return any((root / "roles" / app / name).is_file() for name in names)


class _Fixture:
    root: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        fixture(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()


class TestTheFixtureHoldsEveryRoleSheet(_Fixture, unittest.TestCase):
    def test_the_scan_reaches_every_role_and_its_sheets(self) -> None:
        sheets = [app for app in roles() if ships(self.root, app, ROLE_SHEETS)]
        self.assertGreater(len(roles()), 250)
        self.assertGreater(len(sheets), 50)
        self.assertTrue(
            [app for app in roles() if ships(self.root, app, (COSMOS_SHEET,))]
        )

    def test_the_buckets_render_every_role_exactly_once(self) -> None:
        rendered = [app for bucket in ROLE_BUCKETS for app in bucket]
        self.assertEqual(sorted(rendered), roles())
        self.assertEqual(len(rendered), len(set(rendered)))


class _WithoutAnActiveProviderEveryRoleSheetStaysByteIdentical(_Fixture):
    """
    Args:
        apps: the roles the class renders.
    """

    apps: ClassVar[tuple[str, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        current, previous = resolve_tasks()[:1], [pre_cosmos_task(cls.root)]
        cls.off, cls.before, cls.on = {}, {}, {}
        for app in cls.apps:
            variants = (
                [(vhost, logo) for vhost in VHOSTS for logo in (True, False)]
                if ships(cls.root, app, ROLE_SHEETS)
                else [(VHOSTS[0], True)]
            )
            for vhost, logo in variants:
                for results, tasks in ((cls.off, current), (cls.before, previous)):
                    results[app, vhost, logo], _ = run_tasks(
                        tasks, app, vhost, logo, root=cls.root
                    )
            cls.on[app], _ = run_tasks(
                current, app, VHOSTS[0], True, root=cls.root, cosmos=COSMOS, sheet=True
            )

    def test_every_role_composes_the_sheet_and_version_it_had_before_cosmos(
        self,
    ) -> None:
        for key, now in self.off.items():
            with self.subTest(app=key[0], vhost=key[1], logo=key[2]):
                self.assertEqual(now, self.before[key])
                self.assertEqual(version(now), version(self.before[key]))
        composed = [key for key, now in self.off.items() if now["app_style_css"]]
        sheets = [app for app in self.apps if ships(self.root, app, ROLE_SHEETS)]
        self.assertEqual(len(composed), 4 * len(sheets))

    def test_an_active_provider_changes_exactly_the_roles_that_ship_a_cosmos_sheet(
        self,
    ) -> None:
        changed = [
            app
            for app, now in self.on.items()
            if version(now) != version(self.before[app, VHOSTS[0], True])
        ]
        shipping = [app for app in self.apps if ships(self.root, app, (COSMOS_SHEET,))]
        self.assertEqual(changed, shipping)


ROLE_BUCKETS = buckets(roles(), 6)
for _index, _bucket in enumerate(ROLE_BUCKETS):
    register(
        globals(),
        f"TestWithoutAnActiveProviderEveryRoleSheetStaysByteIdentical_bucket_{_index}",
        _WithoutAnActiveProviderEveryRoleSheetStaysByteIdentical,
        apps=_bucket,
    )


if __name__ == "__main__":
    unittest.main()
