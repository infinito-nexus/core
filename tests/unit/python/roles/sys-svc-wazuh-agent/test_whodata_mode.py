import base64
import unittest

import jinja2

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-svc-wazuh-agent"
NAMES = (
    "WAZUH_AGENT_FIM_WHODATA_MODE",
    "WAZUH_AGENT_BPF_LSM",
    "WAZUH_AGENT_FIM_WHODATA_ACTIVE",
)


def _bool(value):
    return (
        value
        if isinstance(value, bool)
        else str(value).strip().lower() in ("true", "yes", "1")
    )


class TestWhodataMode(unittest.TestCase):
    def active(self, enabled, lsm):
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - renders Ansible expressions from YAML, never HTML
        env.filters["bool"] = _bool
        env.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
        role_vars = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
        values = {
            "WAZUH_AGENT_FIM_WHODATA_ENABLED": enabled,
            "wazuh_agent_lsm": {}
            if lsm is None
            else {"content": base64.b64encode(lsm.encode()).decode()},
        }
        for name in NAMES:
            values[name] = env.from_string(role_vars[name]).render(values)
        return _bool(values["WAZUH_AGENT_FIM_WHODATA_ACTIVE"])

    def test_auto_follows_bpf_lsm(self):
        self.assertTrue(self.active("auto", "lockdown,capability,bpf,landlock\n"))
        self.assertFalse(
            self.active("auto", "lockdown,capability,landlock,yama,apparmor\n")
        )
        self.assertFalse(self.active("auto", None))

    def test_explicit_switch_wins(self):
        self.assertTrue(self.active(True, "lockdown,capability\n"))
        self.assertFalse(self.active(False, "lockdown,bpf\n"))


if __name__ == "__main__":
    unittest.main()
