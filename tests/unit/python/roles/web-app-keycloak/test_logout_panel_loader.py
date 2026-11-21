from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from plugins.filter.text_filters import to_one_liner
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.i18n.extract import logout_context
from utils.i18n.keyed import keyed_catalogue
from utils.networks.reachability import TOR, network
from utils.roles.mapping import ROLE_FILE_META_FORMS

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
LOADER = ROLE / "templates" / "javascript.js.j2"
ASSEMBLY = ROLE / "templates" / "logout-panel.js.j2"
PANEL = ROLE / "files" / "javascript" / "logout-panel.js"
CATALOGUE = ROLE / "files" / "logout_i18n.yml"
NGINX = ROLE / "templates" / "nginx" / "logout_panel.conf.j2"
FIELD_LOCK_NGINX = ROLE / "templates" / "nginx" / "field_lock.conf.j2"
FORMS = ROLE / ROLE_FILE_META_FORMS
ORIGIN = "https://logout.example.test"
EVERYWHERE = "https://dashboard.example.test/#logout-everywhere"
LOGOUT_PATH = "/realms/x/protocol/openid-connect/logout"
ADMIN_PATH = "/admin/master/console/"
BUDGET_BYTES = 2048


def _render_panel() -> str:
    """Assemble what stack_host_template writes and nginx then serves."""
    source = read_text(str(ASSEMBLY))
    catalogue = json.dumps(
        keyed_catalogue(
            PROJECT_ROOT, logout_context, load_yaml(CATALOGUE), PROJECT_ROOT, "core"
        ),
        ensure_ascii=False,
    )

    def resolve(match: re.Match) -> str:
        expression = match.group(0)
        if "KEYCLOAK_LOGOUT_I18N" in expression:
            return catalogue
        if "KEYCLOAK_LOGOUT_EVERYWHERE_URL" in expression:
            return json.dumps(EVERYWHERE)
        if "javascript/logout-panel.js" in expression:
            return read_text(str(PANEL))
        if "'tls'" in expression:
            return json.dumps(ORIGIN)
        if "network_suffix" in expression:
            return json.dumps(network(TOR).suffix)
        raise AssertionError(f"unrenderable expression in the assembly: {expression}")

    return re.sub(r"\{\{.*?\}\}", resolve, source, flags=re.DOTALL)


def _render_loader() -> str:
    digest = hashlib.sha1(_render_panel().encode(), usedforsecurity=False).hexdigest()
    english = load_yaml(CATALOGUE)
    source = read_text(str(LOADER))
    source = re.sub(r"\{%-.*?-%\}", "", source, flags=re.DOTALL)

    def resolve(match: re.Match) -> str:
        expression = match.group(0)
        for key in ("no_check_hint", "no_check"):
            if key in expression:
                return json.dumps(english[key], ensure_ascii=False)
        if "field_pages" in expression:
            return json.dumps(_field_pages())
        return digest

    return to_one_liner(re.sub(r"\{\{.*?\}\}", resolve, source, flags=re.DOTALL))


def _field_pages() -> list[str]:
    return sorted(
        {re.sub(r"[?#].*$", "", form["path"]) for form in load_yaml(FORMS).values()}
    )


def _have_node() -> bool:
    return shutil.which("node") is not None


class TestLoaderShape(unittest.TestCase):
    def test_the_loader_stays_far_below_the_panel_it_replaces(self) -> None:
        size = len(_render_loader().encode())
        self.assertLess(
            size,
            BUDGET_BYTES,
            "the loader rides on every Keycloak page; growing it defeats the split",
        )

    def test_the_loader_carries_no_catalogue(self) -> None:
        loader = _render_loader()
        for word in ("Signing you out", "abgemeldet", "st_done"):
            self.assertNotIn(word, loader, "translations belong in the fetched panel")

    def test_the_requested_url_matches_what_nginx_serves(self) -> None:
        requested = re.search(r'src = "([^"]+)"', _render_loader())
        self.assertIsNotNone(requested, "the loader must request a panel")

        pattern = re.search(r"location\s+~\s+\^(\S+)\$", read_text(str(NGINX)))
        self.assertIsNotNone(
            pattern, "the nginx snippet must match on a regex location"
        )
        self.assertRegex(requested.group(1), pattern.group(1).replace("\\.", r"\."))

    def test_the_field_lock_url_matches_what_nginx_serves(self) -> None:
        requested = re.search(r'src = "(/infinito/field-lock[^"]+)"', _render_loader())
        self.assertIsNotNone(requested, "the loader must request the field lock")

        pattern = re.search(
            r"location\s+~\s+\^(\S+)\$", read_text(str(FIELD_LOCK_NGINX))
        )
        self.assertIsNotNone(
            pattern, "the nginx snippet must match on a regex location"
        )
        self.assertRegex(requested.group(1), pattern.group(1).replace("\\.", r"\."))
        self.assertIn("immutable", read_text(str(FIELD_LOCK_NGINX)))

    def test_the_cache_entry_is_busted_by_content(self) -> None:
        first = _render_loader()
        digest = re.search(r"logout-panel\.([0-9a-f]+)\.js", first).group(1)
        self.assertEqual(
            digest,
            hashlib.sha1(_render_panel().encode(), usedforsecurity=False).hexdigest(),
        )
        self.assertIn(
            "immutable", read_text(str(NGINX)), "immutable needs a busted URL"
        )


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestLoaderBehaviour(unittest.TestCase):
    DOM = """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");

    function element() {
      const node = {
        children: [], style: { cssText: "" }, attrs: {}, id: "", textContent: "",
        setAttribute(k, v) { this.attrs[k] = v; },
        appendChild(child) { this.children.push(child); return child; },
      };
      return node;
    }

    function run(pathname) {
      const appended = [];
      const body = element();
      const head = { appendChild: (node) => { appended.push(node); return node; } };
      let planted = null;
      global.document = {
        createElement: () => element(),
        getElementById: () => planted,
        querySelector: () => null,
        head,
        documentElement: head,
        body,
      };
      global.window = { location: { pathname } };
      eval(script);
      return { appended, body, plant: (v) => { planted = v; } };
    }
    """

    DRIVER = """
    assert.strictEqual(run("/realms/x/account").appended.length, 0, "no fetch off the logout path");
    assert.strictEqual(run("/realms/x/protocol/openid-connect/auth").appended.length, 0, "not on login");

    const r = run(process.argv[3]);
    assert.strictEqual(r.appended.length, 1, "exactly one panel request on the logout page");
    assert.match(r.appended[0].src, /^\\/infinito\\/logout-panel\\.[0-9a-f]+\\.js$/);
    assert.strictEqual(r.appended[0].defer, true, "the panel must not block rendering");

    assert.strictEqual(r.body.children.length, 0, "nothing is drawn while the panel may still load");
    r.appended[0].onerror();
    assert.strictEqual(r.body.children.length, 1, "a panel that cannot load must still say so");
    const stranded = r.body.children[0];
    assert.strictEqual(stranded.attrs["role"], "status");
    assert.match(stranded.children[0].textContent, /[A-Za-z]/, "the message carries text");
    assert.ok(stranded.children[1].textContent.length > 10, "and a way out");

    console.log("OK");
    """

    FIELD_LOCK_DRIVER = """
    const admin = run(process.argv[3]);
    assert.strictEqual(admin.appended.length, 1, "exactly one field lock request on the admin console");
    assert.match(admin.appended[0].src, /^\\/infinito\\/field-lock\\.[0-9a-f]+\\.js$/);
    assert.strictEqual(admin.appended[0].defer, true, "the field lock must not block rendering");
    for (const path of ["/realms/x/account", "/realms/x/protocol/openid-connect/auth", process.argv[4]]) {
      assert.ok(run(path).appended.every((tag) => !/field-lock/.test(tag.src)), "no field lock off the admin console");
    }

    console.log("OK");
    """

    def _node(self, driver_text: str, *paths: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "loader.js"
            stub.write_text(_render_loader())
            driver = Path(tmp) / "driver.js"
            driver.write_text(self.DOM + driver_text)

            proc = subprocess.run(
                ["node", str(driver), str(stub), *paths],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_the_loader_only_acts_on_the_logout_page(self) -> None:
        self._node(self.DRIVER, LOGOUT_PATH)

    def test_the_loader_fetches_the_field_lock_only_on_the_admin_console(
        self,
    ) -> None:
        self._node(self.FIELD_LOCK_DRIVER, ADMIN_PATH, LOGOUT_PATH)


if __name__ == "__main__":
    unittest.main()
