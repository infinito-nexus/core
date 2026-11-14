from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from ansible.plugins.lookup import LookupBase
from jinja2 import Environment

import plugins.lookup.network_handover as network_handover
from plugins.filter.text_filters import to_one_liner
from utils.cache.applications import get_application_defaults
from utils.cache.files import PROJECT_ROOT, read_text
from utils.domains.default_primary import default_domain_primary
from utils.roles.applications.config import get

ROLE = PROJECT_ROOT / "roles" / "web-app-pihole"
SCRIPT = ROLE / "templates" / "javascript.js.j2"
CLEARNET_DOMAIN = f"pihole.{default_domain_primary()}"
ONION_DOMAIN = "pihole." + "a" * 56 + ".onion"

DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");
    const DENIED = "You don't have permission to access this URL."
      + " Did you mean to go to your Pi-hole's dashboard instead?";

    function load(opts) {
      const replaced = [];
      const ready = [];
      global.document = {
        readyState: opts.readyState || "complete",
        body: {
          classList: { contains: (name) => (opts.bodyClasses || []).includes(name) },
          innerText: opts.text || "",
        },
        documentElement: {},
        querySelector: (selector) => (selector === "p" && opts.text ? {} : null),
        getElementById: () => null,
        addEventListener(type, fn) { if (type === "DOMContentLoaded") { ready.push(fn); } },
      };
      global.window = {
        location: { pathname: opts.path, replace: (url) => { replaced.push(url); } },
      };
      global.MutationObserver = class { observe() {} };
      eval(script);
      return { replaced, domReady() { ready.forEach((fn) => fn()); } };
    }

    (function deniedPageOutsideHomeGoesHome() {
      const page = load({ path: "/", bodyClasses: ["login-page", "page-error403"], text: DENIED });
      assert.deepStrictEqual(page.replaced, ["/admin/"]);
    })();

    (function deniedHomeNeverReloadsItself() {
      const page = load({ path: "/admin/", bodyClasses: ["login-page", "page-error403"], text: DENIED });
      assert.deepStrictEqual(page.replaced, [], "a 403 on /admin/ itself reloads /admin/ forever");
    })();

    (function regularPageNamingYourPiholeStays() {
      const page = load({
        path: "/admin/groups/clients",
        bodyClasses: ["hold-transition", "sidebar-mini", "logged-in"],
        text: "Clients that are not assigned to a group use your Pi-hole's default group.",
      });
      assert.deepStrictEqual(page.replaced, [], "a help text phrase is no access denial");
    })();

    (function waitsForTheDomWhenInjectedIntoHead() {
      const page = load({ path: "/", readyState: "loading", bodyClasses: ["page-error403"], text: DENIED });
      assert.deepStrictEqual(page.replaced, []);
      page.domReady();
      assert.deepStrictEqual(page.replaced, ["/admin/"]);
    })();

    console.log("OK");
    """
)


def _served_script() -> str:
    template = Environment(autoescape=True).from_string(read_text(str(SCRIPT)))
    return to_one_liner(template.render())


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestAccessDeniedRedirect(unittest.TestCase):
    def test_only_the_403_page_outside_home_redirects_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "javascript.js"
            script.write_text(_served_script())
            driver = Path(tmp) / "driver.js"
            driver.write_text(DRIVER)
            proc = subprocess.run(
                ["node", str(driver), str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)


class _Answer(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _vhost_hands_over(domain: str) -> bool:
    applications = get_application_defaults()

    def _config(app, path, default):
        return get(applications, app, path, strict=False, default=default)

    answers = {"config": _config, "domain": lambda _app: CLEARNET_DOMAIN}
    loader = mock.MagicMock()
    loader.get.side_effect = lambda name, **_kwargs: _Answer(answers[name])
    lookup = network_handover.LookupModule()
    with mock.patch.object(network_handover, "lookup_loader", loader):
        return lookup.run([ROLE.name, domain], variables={"domain": domain})[0]


class TestOnionHandover(unittest.TestCase):
    def test_the_onion_vhost_hands_over_to_the_one_ftl_webserver_domain(self) -> None:
        self.assertIs(_vhost_hands_over(ONION_DOMAIN), True)

    def test_the_clearnet_vhost_keeps_serving(self) -> None:
        self.assertIs(_vhost_hands_over(CLEARNET_DOMAIN), False)


if __name__ == "__main__":
    unittest.main()
