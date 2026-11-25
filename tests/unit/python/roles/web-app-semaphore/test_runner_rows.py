from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import PurePosixPath

import jinja2

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)
from utils.runner.semaphore import pool_runner_token

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
RUNNER_SERVICE_REF = "{{ SEMAPHORE_RUNNER_SERVICE }}"
WANTED = [
    {"name": "semaphore-runner", "project": "Infinito.Nexus", "tag": "app-control"},
    {
        "name": "semaphore-runner-deploy",
        "project": "Infinito.Nexus Deploy",
        "tag": "deploy",
    },
    {
        "name": "semaphore-runner-workspaces",
        "project": "Infinito.Nexus Workspaces",
        "tag": "workspaces",
    },
    {
        "name": "semaphore-runner-provision",
        "project": "Infinito.Nexus Provision",
        "tag": "provision",
    },
    {
        "name": "semaphore-runner-export",
        "project": "Infinito.Nexus Export",
        "tag": "export",
    },
]
WORKSPACE = {"name": "ws-1", "project": "ws-1", "tags": ["ws-1"]}
POOL_PROJECT = "Infinito.Nexus Pool"
POOL = [
    {"name": f"runner-{index}", "project": POOL_PROJECT, "tag": "pool"}
    for index in (1, 2, 3)
]


def load_module():
    """Returns:
    The role's ``semaphore_runner`` filter plugin module.
    """
    path = ROLE / "filter_plugins" / "semaphore_runner.py"
    spec = importlib.util.spec_from_file_location("semaphore_runner_filter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_filter():
    """Returns:
    ``semaphore_runner_findings`` of the role's filter plugin.
    """
    return load_module().semaphore_runner_findings


def render_rows(runners):
    """Args:
    runners: the rows ``runners.sql.j2`` seeds.

    Returns:
        The rendered SQL, with the pool project of the role's vars.
    """
    template = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        trim_blocks=True,
        undefined=jinja2.StrictUndefined,
    ).from_string(
        read_text(str(ROLE / "templates" / "sql" / "project" / "runners.sql.j2"))
    )
    return template.render(
        SEMAPHORE_RUNNER_ROWS=runners, SEMAPHORE_POOL_PROJECT_NAME=POOL_PROJECT
    )


def lines(rows):
    """Args:
    rows: runner rows as ``runners.sql.j2`` reports them.

    Returns:
        The stdout lines of the post-converge query, with a change line first.
    """
    return ["CHANGED runner semaphore-runner realigned"] + [
        "RUNNER " + json.dumps(row) for row in rows
    ]


def aligned():
    """Returns:
    One row per platform runner in its own project with its own tag, and one
    workspace runner.
    """
    return [
        {"name": r["name"], "project": r["project"], "tags": [r["tag"]]} for r in WANTED
    ] + [WORKSPACE]


class TestRunnerRows(unittest.TestCase):
    def setUp(self):
        self.findings = load_filter()
        self.vars = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
        self.services = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
        self.volumes = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
        self.runners = self.vars["SEMAPHORE_PLATFORM_RUNNERS"]

    def test_the_post_converge_check_refuses_a_runner_without_a_project(self):
        self.assertEqual(self.findings(lines(aligned()), WANTED), [])
        rows = [*aligned(), {"name": "global", "project": None, "tags": []}]
        self.assertEqual(
            self.findings(lines(rows), WANTED), ["runner global has no project"]
        )

    def test_each_platform_project_has_exactly_one_runner(self):
        self.assertEqual(self.findings(lines(aligned()), WANTED), [])
        self.assertEqual(
            [r["key"] for r in self.runners],
            ["app_control", "deploy", "workspaces", "provision", "export"],
        )
        self.assertEqual(
            {r["key"]: r["max_parallel_tasks"] for r in self.runners}["workspaces"], 2
        )

    def test_negative_control_a_second_runner_in_a_platform_project_is_reported(self):
        rows = [
            *aligned(),
            {"name": "spare", "project": "Infinito.Nexus Deploy", "tags": ["deploy"]},
        ]
        self.assertEqual(
            self.findings(lines(rows), WANTED),
            [
                (
                    "project Infinito.Nexus Deploy runs on ['semaphore-runner-deploy', 'spare'], "
                    "expected only semaphore-runner-deploy"
                )
            ],
        )

    def test_negative_control_a_missing_runner_is_reported(self):
        rows = [row for row in aligned() if row["name"] != "semaphore-runner-export"]
        self.assertEqual(
            self.findings(lines(rows), WANTED),
            [
                "project Infinito.Nexus Export runs on [], expected only semaphore-runner-export"
            ],
        )

    def test_negative_control_a_runner_with_another_tag_is_reported(self):
        rows = aligned()
        rows[0]["tags"] = ["app-control", "deploy"]
        self.assertEqual(
            self.findings(lines(rows), WANTED),
            [
                "runner semaphore-runner carries ['app-control', 'deploy'], expected ['app-control']"
            ],
        )

    def test_each_platform_runner_has_its_own_container_and_token_file(self):
        services = [
            r["service"].replace(
                RUNNER_SERVICE_REF, self.vars["SEMAPHORE_RUNNER_SERVICE"]
            )
            for r in self.runners
        ]
        names = [self.services[s]["name"] for s in services]
        tokens = [
            PurePosixPath(r["token_file_host"].split("'")[-2]).name
            for r in self.runners
        ]
        sources = [self.volumes[r["volume"]]["source"] for r in self.runners]
        credentials = [
            r["token"].split("credentials.")[1].split("'")[0] for r in self.runners
        ]
        for values in (services, names, tokens, credentials):
            self.assertEqual(len(set(values)), len(self.runners), values)
        for token, source in zip(tokens, sources, strict=True):
            self.assertIn(f"'{token}'", source)

    def test_the_converge_aligns_the_rows_and_fails_on_a_finding(self):
        converge = read_text(str(ROLE / "tasks" / "utils" / "project" / "converge.yml"))
        self.assertIn("lookup('template', 'sql/project/runners.sql.j2')", converge)
        self.assertIn(
            "semaphore_project_runners.stdout_lines | semaphore_runner_findings(SEMAPHORE_RUNNER_ROWS)",
            converge,
        )
        self.assertEqual(
            self.vars["SEMAPHORE_RUNNER_ROWS"],
            "{{ SEMAPHORE_PLATFORM_RUNNERS_ACTIVE + SEMAPHORE_POOL_RUNNERS }}",
        )
        prepare = read_text(
            str(ROLE / "templates" / "sql" / "project" / "prepare.sql.j2")
        )
        self.assertNotIn("public.runner", prepare)

    def test_the_rows_sql_names_every_active_runner_with_its_project_and_limit(self):
        runners = [
            {
                **r,
                "token": f"t{index}'",
                "max_parallel_tasks": 2 if r["tag"] == "workspaces" else 0,
            }
            for index, r in enumerate(WANTED)
        ]
        sql = render_rows(runners)
        self.assertIn(
            "('semaphore-runner-workspaces', 't2''', 'Infinito.Nexus Workspaces', 'workspaces', 2),",
            sql,
        )
        self.assertIn(
            "('semaphore-runner-export', 't4''', 'Infinito.Nexus Export', 'export', 0);",
            sql,
        )


class TestPoolRunnerRows(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.findings = self.module.semaphore_runner_findings
        self.vars = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))

    def pool_rows(self):
        return [
            {"name": r["name"], "project": r["project"], "tags": [r["tag"]]}
            for r in POOL
        ]

    def test_every_pool_runner_is_seeded_in_the_pool_project_with_one_task(self):
        rows = self.module.semaphore_pool_runners(
            3, "runner", "secret", POOL_PROJECT, "pool"
        )
        self.assertEqual([row["name"] for row in rows], [r["name"] for r in POOL])
        self.assertEqual({row["project"] for row in rows}, {POOL_PROJECT})
        self.assertEqual({row["tag"] for row in rows}, {"pool"})
        self.assertEqual({row["max_parallel_tasks"] for row in rows}, {1})
        self.assertEqual(
            [row["token"] for row in rows],
            [pool_runner_token("secret", r["name"]) for r in POOL],
        )
        self.assertEqual(len({row["token"] for row in rows}), 3)

    def test_the_pool_tag_and_project_are_their_own(self):
        tags = self.vars["SEMAPHORE_PLATFORM_RUNNER_TAGS"]
        self.assertEqual(tags["pool"], "pool")
        self.assertEqual(len(set(tags.values())), len(tags))
        self.assertIn(
            "SEMAPHORE_POOL_ENABLED | bool else []", self.vars["SEMAPHORE_POOL_RUNNERS"]
        )

    def test_the_pool_project_runs_on_exactly_its_pool_runners(self):
        wanted = [*WANTED, *POOL]
        rows = [*aligned(), *self.pool_rows()]
        self.assertEqual(self.findings(lines(rows), wanted), [])

    def test_negative_control_a_missing_pool_runner_is_reported(self):
        wanted = [*WANTED, *POOL]
        rows = [*aligned(), *self.pool_rows()[:2]]
        self.assertEqual(
            self.findings(lines(rows), wanted),
            [
                (
                    f"project {POOL_PROJECT} runs on ['runner-1', 'runner-2'], "
                    "expected only runner-1, runner-2, runner-3"
                )
            ],
        )

    def test_negative_control_a_pool_runner_with_another_tag_is_reported(self):
        wanted = [*WANTED, *POOL]
        rows = [*aligned(), *self.pool_rows()]
        rows[-1]["tags"] = ["deploy"]
        self.assertEqual(
            self.findings(lines(rows), wanted),
            ["runner runner-3 carries ['deploy'], expected ['pool']"],
        )

    def test_the_rows_sql_seeds_the_pool_and_prunes_what_it_no_longer_runs(self):
        runners = [
            {**r, "token": f"p{index}", "max_parallel_tasks": 1}
            for index, r in enumerate(POOL)
        ]
        sql = render_rows(runners)
        self.assertIn(
            f"('runner-3', 'p2', '{POOL_PROJECT}', 'pool', 1);",
            sql,
        )
        self.assertIn(f"\\set pool_project '{POOL_PROJECT}'", sql)
        self.assertEqual(sql.count("project.name = :'pool_project'"), 2)
        self.assertIn("' removed';", sql)


if __name__ == "__main__":
    unittest.main()
