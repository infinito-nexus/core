from __future__ import annotations

import configparser
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "sys-svc-journalctl"
SERVICE = "svc-journalctl"


def configured(key: str):
    """
    Args:
        key: a setting of the role's service in meta/services.yml.

    Returns:
        Its configured value.
    """
    return load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))[SERVICE][key]


def journal_section() -> configparser.SectionProxy:
    """
    Returns:
        The [Journal] section of the rendered journald.conf.
    """
    template = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    ).from_string(read_text(str(ROLE / "templates" / "journald.conf.j2")))
    rendered = template.render(
        sys_svc_journalctl_filesystem={"stdout_lines": ["1M-blocks", "10240"]},
        SYS_SVC_JOURNALCTL_SYSTEM_MAX_USE_PERCENT=configured("system_max_use_percent"),
        SYS_SVC_JOURNALCTL_SYSTEM_KEEP_FREE=configured("system_keep_free"),
        SYS_SVC_JOURNALCTL_MAX_RETENTION_SEC=configured("max_retention_sec"),
    )
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(rendered)
    return parser["Journal"]


class TestRetentionBound(unittest.TestCase):
    def test_entries_are_deleted_after_the_configured_retention(self) -> None:
        self.assertEqual(
            journal_section()["MaxRetentionSec"],
            str(configured("max_retention_sec")),
        )

    def test_the_active_file_is_archived_daily(self) -> None:
        self.assertEqual(
            journal_section().get("MaxFileSec"),
            "1day",
            "MaxRetentionSec deletes only archived files; with the default "
            "MaxFileSec of one month the active file keeps entries for a month",
        )


if __name__ == "__main__":
    unittest.main()
