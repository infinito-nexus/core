from __future__ import annotations

import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.applications.forms import is_lock_pending, locks
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

APPLICATION = "web-app-stalwart"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
SECURITY_TASKS = ROLE / "tasks" / "security.yml"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
RESOLVE = "stalwart_ban_periods_current"
APPLY = "security/apply.yml"
SECONDS = 60
BAN_FIELDS = ("authBanPeriod", "abuseBanPeriod", "loiterBanPeriod", "scanBanPeriod")


class _Config(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION, "services.stalwart.ban_period_seconds"]:
            raise AssertionError(f"read {terms}")
        return [SECONDS]


def _forms() -> dict:
    return load_yaml_any(str(FORMS), default_if_missing={})


def _services() -> dict:
    return DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)


def _application(period_ms: int) -> dict:
    stalwart = _services()["stalwart"]
    return {
        "services": {
            "stalwart": {
                "bans": {"period_ms": period_ms},
                "client_ip": dict(stalwart["client_ip"]),
            }
        }
    }


def _tasks() -> list[dict]:
    return load_yaml_any(str(SECURITY_TASKS), default_if_missing=[])


def _index(fragment: str) -> int:
    return next(index for index, task in enumerate(_tasks()) if fragment in str(task))


class TestSecurityForms(unittest.TestCase):
    def test_the_computed_ban_period_is_the_inventory_seconds_in_ms(self) -> None:
        real_get = lookup_loader.get

        def get(name, *args, **kwargs):
            return _Config() if name == "config" else real_get(name, *args, **kwargs)

        templar = Templar(loader=DataLoader(), variables={})
        with mock.patch.object(lookup_loader, "get", side_effect=get):
            bans = templar.template(_services()["stalwart"]["bans"])
        self.assertEqual({"period_ms": SECONDS * 1000}, bans)

    def test_the_forms_carry_the_settings_the_converge_wrote_before(self) -> None:
        application = _application(SECONDS * 1000)
        self.assertEqual(
            dict.fromkeys(BAN_FIELDS, SECONDS * 1000),
            values("security", _forms(), application, {}),
        )
        self.assertEqual(
            {"clientIpSource": "forwarded", "forwardedHops": 1},
            values("http", _forms(), application, {}),
        )

    def test_no_lock_reaches_the_webui_yet_and_an_issue_tracks_it(self) -> None:
        forms = _forms()
        for form in ("security", "http"):
            with self.subTest(form=form):
                self.assertTrue(is_lock_pending(forms[form]))
        self.assertEqual(
            [], locks(APPLICATION, forms, _application(SECONDS * 1000), {}, {})
        )

    def test_each_sink_reads_only_its_form(self) -> None:
        variables = load_yaml_any(str(VARS))
        for sink, form in (
            ("STALWART_BAN_PERIODS", "security"),
            ("STALWART_HTTP_SETTINGS", "http"),
        ):
            with self.subTest(sink=sink):
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    variables[sink],
                )

    def test_the_drift_report_runs_after_the_read_and_before_the_apply(self) -> None:
        resolve = _index(RESOLVE)
        report = _index(DRIFT_TASKS)
        apply = _index(APPLY)
        self.assertLess(resolve, report)
        self.assertLess(report, apply)
        self.assertEqual(
            {
                "security": "{{ stalwart_ban_periods_current }}",
                "http": "{{ stalwart_http_settings_current }}",
            },
            _tasks()[report]["vars"]["forms_drift_current"],
        )


if __name__ == "__main__":
    unittest.main()
