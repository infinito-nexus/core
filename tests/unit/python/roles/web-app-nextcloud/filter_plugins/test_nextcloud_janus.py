from __future__ import annotations

import importlib.util
import sys
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

OVERRIDES = ("rtp_port_range", "nat_1_1_mapping", "keep_private_host")
TARGET = "/usr/local/etc/janus/janus.jcfg"
LAUNCHER = (
    "[program:janus]\n"
    "command=janus --config=/usr/local/etc/janus/janus.jcfg --disable-colors"
    " --log-stdout --full-trickle --debug-level 3\n"
)


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-nextcloud/filter_plugins/nextcloud_janus.py", "nextcloud_janus"
)


def _rendered_template() -> str:
    env = Environment(
        loader=FileSystemLoader(
            str(PROJECT_ROOT / "roles/web-app-nextcloud/templates")
        ),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=select_autoescape(default_for_string=False),
    )
    return env.get_template("janus.jcfg.j2").render(
        NEXTCLOUD_HPB_MEDIA_PORT_START=61000,
        NEXTCLOUD_HPB_MEDIA_PORT_END=61999,
        NEXTCLOUD_HPB_MEDIA_PUBLIC_IP="203.0.113.7",
    )


def _stock_like() -> str:
    lines = ["/* a block comment the image ships", "   over two lines */"]
    for line in _rendered_template().splitlines():
        if line.strip().split(" ", 1)[0] in OVERRIDES:
            lines.append("\t#" + line.strip() + "\t\t# commented out upstream")
            continue
        lines.append("\t\t# a comment line the image ships")
        lines.append(line.replace(" = ", "  =  ") + "\t// trailing remark")
    return "\n".join(lines) + "\n"


def _drift(stock: str, launcher: str = LAUNCHER) -> list[str]:
    return MODULE.janus_config_drift(
        _rendered_template(), stock, OVERRIDES, launcher, TARGET
    )


class TestJanusSettings(unittest.TestCase):
    def test_comments_and_blank_lines_are_dropped(self):
        content = "# head\n\ngeneral: {\n\tdebug_level = 4\t\t# level\n}\n"
        self.assertEqual(
            MODULE.janus_settings(content, []), ["general:{", "debug_level=4", "}"]
        )

    def test_block_comments_and_a_trailing_semicolon_are_dropped(self):
        content = "/* head\n tail */\ndebug_level = 4; /* level */\n"
        self.assertEqual(MODULE.janus_settings(content, []), ["debug_level=4"])

    def test_a_hash_inside_a_quoted_value_is_kept(self):
        content = 'log_prefix = "[janus] #1"  # prefix\n'
        self.assertEqual(
            MODULE.janus_settings(content, []), ['log_prefix="[janus] #1"']
        )

    def test_named_overrides_are_left_out(self):
        content = 'nat: {\n\tnat_1_1_mapping = "1.2.3.4"\n\tnice_debug = false\n}\n'
        self.assertEqual(
            MODULE.janus_settings(content, ["nat_1_1_mapping"]),
            ["nat:{", "nice_debug=false", "}"],
        )

    def test_the_template_sets_every_override_once(self):
        keys = [
            setting.split("=", 1)[0]
            for setting in MODULE.janus_settings(_rendered_template(), [])
        ]
        for override in OVERRIDES:
            self.assertEqual(keys.count(override), 1, override)


class TestJanusConfigDrift(unittest.TestCase):
    def test_a_stock_file_that_differs_only_in_comments_and_layout_passes(self):
        self.assertEqual(_drift(_stock_like()), [])

    def test_a_moved_plugin_folder_stops_the_deploy(self):
        stock = _stock_like().replace(
            '"/usr/local/lib/janus/plugins"', '"/usr/lib/janus/plugins"'
        )
        self.assertEqual(len(_drift(stock)), 1)

    def test_an_upstream_value_for_a_masked_key_stops_the_deploy(self):
        stock = _stock_like().replace("\t#rtp_port_range", "\trtp_port_range", 1)
        self.assertEqual(len(_drift(stock)), 1)

    def test_a_setting_upstream_added_stops_the_deploy(self):
        stock = _stock_like().replace("nat: {", "nat: {\n\tice_tcp = true", 1)
        self.assertEqual(len(_drift(stock)), 1)

    def test_an_empty_read_stops_the_deploy(self):
        self.assertEqual(len(_drift("")), 1)

    def test_janus_reading_a_generated_config_stops_the_deploy(self):
        launcher = LAUNCHER.replace(TARGET, "/conf/janus.jcfg")
        self.assertEqual(
            _drift(_stock_like(), launcher),
            [f"Janus is not started with --config={TARGET}"],
        )

    def test_a_config_path_that_only_shares_the_prefix_stops_the_deploy(self):
        launcher = LAUNCHER.replace(f"{TARGET} ", f"{TARGET}.generated ")
        self.assertEqual(len(_drift(_stock_like(), launcher)), 1)

    def test_a_launcher_without_janus_stops_the_deploy(self):
        self.assertEqual(len(_drift(_stock_like(), "")), 1)


if __name__ == "__main__":
    unittest.main()
