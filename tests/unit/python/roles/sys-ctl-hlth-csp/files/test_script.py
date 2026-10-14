from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

ROLE_FILES = PROJECT_ROOT / "roles/sys-ctl-hlth-csp/files/python"
sys.path.insert(0, str(ROLE_FILES))

import script  # noqa: E402


class TestExtractDomainsFromFilenames(unittest.TestCase):
    @patch("script.os.listdir")
    def test_extract_domains_filters_valid_conf_domains(
        self, mock_listdir: MagicMock
    ) -> None:
        mock_listdir.return_value = [
            "example.com.conf",
            "api.example.com.conf",
            "not-a-domain.txt",
            "no-tld.conf",
            ".hidden.conf",
            "a..b.com.conf",
            "example.com.conf.bak",
            "localhost.conf",
            "sub.domain.co.uk.conf",
        ]

        domains = script.extract_domains_from_filenames(
            "/etc/nginx/conf.d/http/servers/"
        )
        self.assertIsInstance(domains, list)

        self.assertIn("example.com", domains)
        self.assertIn("api.example.com", domains)
        self.assertIn("sub.domain.co.uk", domains)

        self.assertNotIn("not-a-domain", domains)
        self.assertNotIn("no-tld", domains)
        self.assertNotIn(".hidden", domains)
        self.assertNotIn("a..b.com", domains)
        self.assertNotIn("example.com.conf", domains)
        self.assertNotIn("localhost", domains)

    @patch("script.os.listdir", side_effect=FileNotFoundError)
    def test_extract_domains_returns_none_when_directory_missing(
        self, _mock_listdir: MagicMock
    ) -> None:
        domains = script.extract_domains_from_filenames("/missing")
        self.assertIsNone(domains)


SUFFIX = ".onion"
DOMAIN = default_domain_primary()


def _vhosts(*domains: str) -> dict[str, Path]:
    return {d: Path("/etc/nginx/servers/http") / f"{d}.conf" for d in domains}


def _argv(*extra: str) -> list[str]:
    return [
        "script.py",
        "--nginx-config-dir",
        "/etc/nginx/servers",
        "--proxy-suffix",
        SUFFIX,
        "--image",
        "img:tag",
        *extra,
    ]


class TestCollectVhosts(unittest.TestCase):
    def test_https_conf_wins_over_the_http_redirect(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for protocol, domain in (
                ("http", f"app.{DOMAIN}"),
                ("https", f"app.{DOMAIN}"),
                ("http", "app.abc123.onion"),
            ):
                (Path(tmp) / protocol).mkdir(exist_ok=True)
                (Path(tmp) / protocol / f"{domain}.conf").write_text("")

            vhosts = script.collect_vhosts(tmp)

        self.assertEqual(vhosts[f"app.{DOMAIN}"].parent.name, "https")
        self.assertEqual(vhosts["app.abc123.onion"].parent.name, "http")

    def test_missing_directories_return_none(self) -> None:
        with patch("sys.stderr"):
            self.assertIsNone(script.collect_vhosts("/definitely/missing"))


class TestSplitProxiedDomains(unittest.TestCase):
    def test_splits_families(self) -> None:
        domains = [
            "auth.abc123.onion",
            f"app.{DOMAIN}",
            "matomo.abc123.onion",
        ]
        clearnet, onion = script.split_proxied_domains(domains, SUFFIX)
        self.assertEqual(clearnet, [f"app.{DOMAIN}"])
        self.assertEqual(onion, ["auth.abc123.onion", "matomo.abc123.onion"])

    def test_clearnet_only(self) -> None:
        domains = ["a.example", "b.example"]
        self.assertEqual(script.split_proxied_domains(domains, SUFFIX), (domains, []))

    def test_empty_list(self) -> None:
        self.assertEqual(script.split_proxied_domains([], SUFFIX), ([], []))

    def test_no_suffix_proxies_nothing(self) -> None:
        domains = ["a.abc123.onion"]
        self.assertEqual(script.split_proxied_domains(domains, ""), (domains, []))


class TestIsSkippedDomain(unittest.TestCase):
    def _skipped(self, domain: str) -> bool:
        skip_set = {f"mirror.{DOMAIN}"}
        labels = {d.split(".", 1)[0] for d in skip_set}
        return script.is_skipped_domain(domain, skip_set, labels, SUFFIX)

    def test_explicit_clearnet_domain_is_skipped(self) -> None:
        self.assertTrue(self._skipped(f"mirror.{DOMAIN}"))

    def test_onion_sibling_of_skipped_clearnet_is_skipped(self) -> None:
        self.assertTrue(self._skipped("mirror.abc123.onion"))

    def test_unrelated_onion_is_not_skipped(self) -> None:
        self.assertFalse(self._skipped("auth.abc123.onion"))

    def test_unrelated_clearnet_is_not_skipped(self) -> None:
        self.assertFalse(self._skipped(f"auth.{DOMAIN}"))


class TestMainSkipsOnionSiblings(unittest.TestCase):
    @patch("script.run_checker")
    @patch("script.build_urls_from_nginx_confs")
    @patch("script.collect_vhosts")
    def test_onion_sibling_of_skip_domain_is_excluded(
        self,
        mock_collect: MagicMock,
        mock_build_urls: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = _vhosts(
            f"mirror.{DOMAIN}",
            "mirror.abc123.onion",
            "auth.abc123.onion",
        )
        mock_build_urls.side_effect = lambda _vhosts, domains: [
            f"http://{d}/" for d in domains
        ]
        mock_run_checker.return_value = 0

        with (
            patch.object(
                script.sys,
                "argv",
                _argv(
                    "--skip-domain",
                    f"mirror.{DOMAIN}",
                    "--tor-proxy",
                    "socks5://127.0.0.1:9050",
                ),
            ),
            self.assertRaises(SystemExit),
        ):
            script.main()

        probed = [d for call in mock_build_urls.call_args_list for d in call.args[1]]
        self.assertNotIn(f"mirror.{DOMAIN}", probed)
        self.assertNotIn("mirror.abc123.onion", probed)
        self.assertIn("auth.abc123.onion", probed)


class TestBuildDockerCmdProxy(unittest.TestCase):
    def test_proxy_arg_appended(self) -> None:
        cmd = script.build_docker_cmd(
            image="img",
            urls=["http://a.onion/"],
            short_mode=True,
            ignore_network_blocks_from=[],
            proxy="socks5://127.0.0.1:9050",
        )
        idx = cmd.index("--proxy")
        self.assertEqual(cmd[idx + 1], "socks5://127.0.0.1:9050")

    def test_no_proxy_arg_without_proxy(self) -> None:
        cmd = script.build_docker_cmd(
            image="img",
            urls=["https://a.example/"],
            short_mode=True,
            ignore_network_blocks_from=[],
        )
        self.assertNotIn("--proxy", cmd)


class TestBuildDockerCmdTimeout(unittest.TestCase):
    def test_timeout_arg_appended(self) -> None:
        cmd = script.build_docker_cmd(
            image="img",
            urls=["http://a.onion/"],
            short_mode=True,
            ignore_network_blocks_from=[],
            timeout_ms=100000,
        )
        idx = cmd.index("--timeout")
        self.assertEqual(cmd[idx + 1], "100000")

    def test_no_timeout_arg_without_one(self) -> None:
        cmd = script.build_docker_cmd(
            image="img",
            urls=["https://a.example/"],
            short_mode=True,
            ignore_network_blocks_from=[],
        )
        self.assertNotIn("--timeout", cmd)

    def test_the_timeout_precedes_the_url_separator(self) -> None:
        cmd = script.build_docker_cmd(
            image="img",
            urls=["http://a.onion/"],
            short_mode=True,
            ignore_network_blocks_from=["cdn.example"],
            timeout_ms=100000,
        )
        self.assertLess(
            cmd.index("--timeout"),
            cmd.index("--"),
            "an argument after the separator reaches the checker as a URL",
        )


class TestMainTimesOutOnionsOnly(unittest.TestCase):
    @patch("script.run_checker")
    @patch("script.build_urls_from_nginx_confs")
    @patch("script.collect_vhosts")
    def test_the_onion_batch_alone_carries_the_budget(
        self,
        mock_collect: MagicMock,
        mock_build_urls: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = _vhosts(f"auth.{DOMAIN}", "auth.abc123.onion")
        mock_build_urls.side_effect = lambda _vhosts, domains: [
            f"http://{d}/" for d in domains
        ]
        mock_run_checker.return_value = 0

        with (
            patch.object(
                script.sys,
                "argv",
                _argv(
                    "--tor-proxy",
                    "socks5://127.0.0.1:9050",
                    "--onion-timeout",
                    "100000",
                ),
            ),
            self.assertRaises(SystemExit),
        ):
            script.main()

        budgets = {
            call.kwargs["urls"][0]: call.kwargs["timeout_ms"]
            for call in mock_run_checker.call_args_list
        }
        self.assertEqual(budgets["http://auth.abc123.onion/"], 100000)
        self.assertEqual(budgets[f"http://auth.{DOMAIN}/"], 0)


class TestDetectSchemeFromConf(unittest.TestCase):
    def test_detects_https_via_443(self) -> None:
        with patch("pathlib.Path.read_text", return_value="listen 443 ssl;"):
            self.assertEqual(script.detect_scheme_from_conf(Path("x.conf")), "https")

    def test_detects_https_via_ssl_flag(self) -> None:
        with patch("pathlib.Path.read_text", return_value="listen 8443 ssl;"):
            self.assertEqual(script.detect_scheme_from_conf(Path("x.conf")), "https")

    def test_detects_http_via_80(self) -> None:
        with patch("pathlib.Path.read_text", return_value="listen 80;"):
            self.assertEqual(script.detect_scheme_from_conf(Path("x.conf")), "http")

    def test_detects_none_when_no_listen_lines(self) -> None:
        with patch("pathlib.Path.read_text", return_value="server_name example.com;"):
            self.assertIsNone(script.detect_scheme_from_conf(Path("x.conf")))

    def test_ignores_comments_and_blank_lines(self) -> None:
        conf = """
# listen 443 ssl;

    # listen 80;
    server_name example.com;
"""
        with patch("pathlib.Path.read_text", return_value=conf):
            self.assertIsNone(script.detect_scheme_from_conf(Path("x.conf")))

    def test_returns_none_when_file_missing(self) -> None:
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            self.assertIsNone(script.detect_scheme_from_conf(Path("missing.conf")))


class TestBuildUrlsFromNginxConfs(unittest.TestCase):
    @patch("script.detect_scheme_from_conf")
    def test_build_urls_https_preferred(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = "https"

        urls = script.build_urls_from_nginx_confs(
            _vhosts("example.com"), ["example.com"]
        )
        self.assertEqual(urls, ["https://example.com/"])

    @patch("script.detect_scheme_from_conf")
    def test_build_urls_http_when_http_detected(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = "http"

        urls = script.build_urls_from_nginx_confs(
            _vhosts("example.com"), ["example.com"]
        )
        self.assertEqual(urls, ["http://example.com/"])

    @patch("script.detect_scheme_from_conf")
    def test_build_urls_falls_back_to_http_and_warns(
        self, mock_detect: MagicMock
    ) -> None:
        mock_detect.return_value = None

        with patch("sys.stderr") as _stderr:
            urls = script.build_urls_from_nginx_confs(
                _vhosts("example.com"), ["example.com"]
            )

        self.assertEqual(urls, ["http://example.com/"])


class TestBuildDockerCmd(unittest.TestCase):
    def test_build_docker_cmd_defaults_to_host_network_and_root_user(self) -> None:
        cmd = script.build_docker_cmd(
            image="ghcr.io/kevinveenbirkenbach/csp-checker:stable",
            urls=["http://example.com/"],
            short_mode=False,
            ignore_network_blocks_from=[],
        )

        self.assertEqual(cmd[0:3], ["container", "run", "--rm"])

        self.assertIn("--user", cmd)
        uidx = cmd.index("--user")
        self.assertEqual(cmd[uidx + 1], "0:0")

        self.assertIn("--network", cmd)
        nidx = cmd.index("--network")
        self.assertEqual(cmd[nidx + 1], "host")

        self.assertIn("ghcr.io/kevinveenbirkenbach/csp-checker:stable", cmd)
        self.assertEqual(cmd[-1], "http://example.com/")

    def test_build_docker_cmd_can_disable_host_network(self) -> None:
        cmd = script.build_docker_cmd(
            image="img:tag",
            urls=["http://example.com/"],
            short_mode=False,
            ignore_network_blocks_from=[],
            use_host_network=False,
        )

        self.assertEqual(cmd[0:3], ["container", "run", "--rm"])

        self.assertIn("--user", cmd)
        uidx = cmd.index("--user")
        self.assertEqual(cmd[uidx + 1], "0:0")

        self.assertNotIn("--network", cmd)
        self.assertNotIn("host", cmd)

    def test_build_docker_cmd_short_mode(self) -> None:
        cmd = script.build_docker_cmd(
            image="img:tag",
            urls=["http://example.com/"],
            short_mode=True,
            ignore_network_blocks_from=[],
        )
        self.assertIn("--short", cmd)

    def test_build_docker_cmd_ignore_list_adds_separator_and_urls(self) -> None:
        cmd = script.build_docker_cmd(
            image="img:tag",
            urls=["http://a.example/", "https://b.example/"],
            short_mode=False,
            ignore_network_blocks_from=["pxscdn.com", "cdn.example.org"],
        )

        self.assertIn("--ignore-network-blocks-from", cmd)
        idx = cmd.index("--ignore-network-blocks-from")

        self.assertEqual(cmd[idx + 1], "pxscdn.com")
        self.assertEqual(cmd[idx + 2], "cdn.example.org")
        self.assertEqual(cmd[idx + 3], "--")
        self.assertEqual(cmd[idx + 4 :], ["http://a.example/", "https://b.example/"])


class TestRunChecker(unittest.TestCase):
    @patch("script.subprocess.run")
    def test_run_checker_pulls_image_when_always_pull_true(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=3),
        ]

        rc = script.run_checker(
            image="img:tag",
            urls=["http://example.com/"],
            short_mode=True,
            ignore_network_blocks_from=[],
            always_pull=True,
            use_host_network=True,
        )

        self.assertEqual(rc, 3)
        self.assertGreaterEqual(mock_run.call_count, 2)

        pull_call = mock_run.call_args_list[0]
        self.assertEqual(pull_call.kwargs.get("check"), False)
        self.assertEqual(pull_call.args[0], ["container", "pull", "img:tag"])

        run_call = mock_run.call_args_list[1]
        self.assertEqual(run_call.kwargs.get("check"), False)

        self.assertEqual(run_call.args[0][0:3], ["container", "run", "--rm"])

        self.assertIn("--user", run_call.args[0])
        uidx = run_call.args[0].index("--user")
        self.assertEqual(run_call.args[0][uidx + 1], "0:0")

    @patch("script.subprocess.run")
    def test_run_checker_returns_127_if_run_missing(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError

        rc = script.run_checker(
            image="img:tag",
            urls=["http://example.com/"],
            short_mode=False,
            ignore_network_blocks_from=[],
            always_pull=False,
            use_host_network=True,
        )
        self.assertEqual(rc, 127)

    @patch("script.subprocess.run")
    def test_run_checker_returns_1_on_unexpected_exception(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = RuntimeError("boom")

        rc = script.run_checker(
            image="img:tag",
            urls=["http://example.com/"],
            short_mode=False,
            ignore_network_blocks_from=[],
            always_pull=False,
            use_host_network=True,
        )
        self.assertEqual(rc, 1)


class TestMain(unittest.TestCase):
    @patch("script.run_checker")
    @patch("script.collect_vhosts")
    def test_main_exits_1_when_collect_vhosts_returns_none(
        self,
        mock_collect: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = None

        with (
            patch.object(script.sys, "argv", _argv()),
            self.assertRaises(SystemExit) as cm,
        ):
            script.main()

        self.assertEqual(cm.exception.code, 1)
        mock_run_checker.assert_not_called()

    @patch("script.run_checker")
    @patch("script.collect_vhosts")
    def test_main_exits_0_when_no_domains_found(
        self,
        mock_collect: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = {}

        with (
            patch.object(script.sys, "argv", _argv()),
            self.assertRaises(SystemExit) as cm,
        ):
            script.main()

        self.assertEqual(cm.exception.code, 0)
        mock_run_checker.assert_not_called()

    @patch("script.run_checker")
    @patch("script.build_urls_from_nginx_confs")
    @patch("script.collect_vhosts")
    def test_main_passes_defaults_and_exits_with_run_checker_rc(
        self,
        mock_collect: MagicMock,
        mock_build_urls: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = _vhosts("example.com", "api.example.com")
        mock_build_urls.return_value = [
            "http://example.com/",
            "https://api.example.com/",
        ]
        mock_run_checker.return_value = 5

        with (
            patch.object(
                script.sys,
                "argv",
                _argv(
                    "--short",
                    "--ignore-network-blocks-from",
                    "pxscdn.com",
                    "cdn.example.org",
                ),
            ),
            self.assertRaises(SystemExit) as cm,
        ):
            script.main()

        self.assertEqual(cm.exception.code, 5)

        mock_run_checker.assert_called_once()
        kwargs = mock_run_checker.call_args.kwargs
        self.assertEqual(kwargs["image"], "img:tag")
        self.assertEqual(
            kwargs["urls"], ["http://example.com/", "https://api.example.com/"]
        )
        self.assertTrue(kwargs["short_mode"])
        self.assertEqual(
            kwargs["ignore_network_blocks_from"], ["pxscdn.com", "cdn.example.org"]
        )
        self.assertFalse(kwargs["always_pull"])
        self.assertTrue(kwargs["use_host_network"])

    @patch("script.run_checker")
    @patch("script.build_urls_from_nginx_confs")
    @patch("script.collect_vhosts")
    def test_main_no_host_network_flag_disables_host_network(
        self,
        mock_collect: MagicMock,
        mock_build_urls: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = _vhosts("example.com")
        mock_build_urls.return_value = ["http://example.com/"]
        mock_run_checker.return_value = 0

        with (
            patch.object(script.sys, "argv", _argv("--no-host-network")),
            self.assertRaises(SystemExit) as cm,
        ):
            script.main()

        self.assertEqual(cm.exception.code, 0)

        kwargs = mock_run_checker.call_args.kwargs
        self.assertFalse(kwargs["use_host_network"])

    @patch("script.run_checker")
    @patch("script.build_urls_from_nginx_confs")
    @patch("script.collect_vhosts")
    def test_main_exits_0_when_no_urls_built(
        self,
        mock_collect: MagicMock,
        mock_build_urls: MagicMock,
        mock_run_checker: MagicMock,
    ) -> None:
        mock_collect.return_value = _vhosts("example.com")
        mock_build_urls.return_value = []

        with (
            patch.object(script.sys, "argv", _argv()),
            self.assertRaises(SystemExit) as cm,
        ):
            script.main()

        self.assertEqual(cm.exception.code, 0)
        mock_run_checker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
