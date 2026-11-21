from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-mastodon"
TASKS = ROLE / "tasks" / "06_design.yml"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
SINK = "MASTODON_BRANDING"
DRIFT = "tasks/utils/forms/drift.yml"
LABEL = "Corporate Mastodon"


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _is_report(task: dict) -> bool:
    return DRIFT in str(task.get("ansible.builtin.include_tasks", ""))


def _is_write(task: dict) -> bool:
    return "ruby/design.rb" in str(
        task.get("ansible.builtin.command", {}).get("stdin", "")
    )


def _templar(**variables):
    return Templar(loader=DataLoader(), variables=variables)


def _jinja(expression: str, **variables) -> str:
    def lookup(name: str, *terms: str) -> dict:
        assert name == "design"
        return {"label": LABEL, "title": False}

    return (
        Environment(autoescape=True)
        .from_string(str(expression))
        .render(lookup=lookup, **variables)
    )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks()
        read = _index(tasks, lambda task: "database_query" in task)
        report = _index(tasks, _is_report)
        write = _index(tasks, _is_write)
        self.assertLess(read, report)
        self.assertLess(report, write)

    def test_the_read_asks_for_exactly_the_sink_fields(self) -> None:
        read = next(task for task in _tasks() if "database_query" in task)
        for sink, fields in (({"site_title": LABEL}, ["site_title"]), ({}, [])):
            with self.subTest(sink=sink):
                self.assertEqual(
                    fields,
                    json.loads(
                        _templar(**{SINK: sink}).template(
                            read["database_query"]["named_args"]["fields"]
                        )
                    ),
                )

    def test_the_report_reads_the_yaml_mastodon_stores(self) -> None:
        expression = next(task for task in _tasks() if _is_report(task))["vars"][
            "forms_drift_current"
        ]["branding"]
        for rows, current in (
            ([["site_title", "--- Somebody else\n"]], {"site_title": "Somebody else"}),
            ([], {}),
        ):
            with self.subTest(rows=rows):
                templar = _templar(mastodon_branding_stored={"rows": rows})
                self.assertEqual(current, templar.template(expression))

    def test_the_write_takes_the_title_from_the_sink(self) -> None:
        title = next(task for task in _tasks() if _is_write(task))["vars"][
            "mastodon_design_payload"
        ]["title"]
        self.assertEqual(
            "Sink title", _jinja(title, **{SINK: {"site_title": "Sink title"}})
        )

    def test_without_the_field_the_write_still_knows_the_title_it_retires(self) -> None:
        title = next(task for task in _tasks() if _is_write(task))["vars"][
            "mastodon_design_payload"
        ]["title"]
        self.assertEqual(LABEL, _jinja(title, **{SINK: {}}))


class TestTheFormTakesTheDesignLabel(unittest.TestCase):
    def test_the_source_is_the_design_label(self) -> None:
        source = load_yaml_any(str(SERVICES))["mastodon"]["site_title"]
        self.assertEqual(LABEL, _jinja(source))

    def test_the_field_follows_the_design_service(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for enabled, wanted in ((True, {"site_title": LABEL}), (False, {})):
            with self.subTest(enabled=enabled):
                application = {
                    "services": {
                        "design": {"enabled": enabled},
                        "mastodon": {"site_title": LABEL},
                    }
                }
                self.assertEqual(wanted, values("branding", forms, application, {}))


if __name__ == "__main__":
    unittest.main()
