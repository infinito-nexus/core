import importlib.util
import unittest

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "sys-ctl-hlth-csp" / "files" / "python" / "script.py"
URLS = ["https://a.test/", "https://b.test/"]


def _load():
    spec = importlib.util.spec_from_file_location("csp_wrapper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cmd(**kwargs):
    return _load().build_docker_cmd(
        image="img",
        urls=URLS,
        short_mode=False,
        ignore_network_blocks_from=kwargs.get("ignore", []),
        accept_status=kwargs.get("accept", []),
    )


class TestListFlagsAreSeparatedFromUrls(unittest.TestCase):
    def test_accept_status_is_separated_from_the_urls(self):
        cmd = _cmd(accept=["a.test=403"])

        self.assertEqual(
            cmd[cmd.index("--accept-status") + 2],
            "--",
            "the checker consumes every token after a list flag that does not "
            "start with '--', and a URL does not, so the URLs would be read as "
            "more status declarations",
        )

    def test_two_list_flags_share_a_single_separator(self):
        cmd = _cmd(ignore=["x.test"], accept=["y.test=403"])

        self.assertEqual(cmd.count("--"), 1)
        self.assertLess(cmd.index("--"), cmd.index(URLS[0]))

    def test_without_a_list_flag_no_separator_is_emitted(self):
        self.assertNotIn("--", _cmd())

    def test_every_url_survives_the_separator(self):
        cmd = _cmd(accept=["y.test=403"])

        self.assertEqual(cmd[cmd.index("--") + 1 :], URLS)


if __name__ == "__main__":
    unittest.main()
