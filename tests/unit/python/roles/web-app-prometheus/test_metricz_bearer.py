from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SECRETS

_SPEC = spec_from_file_location(
    "federate_conf_render", Path(__file__).with_name("test_federate_conf.py")
)
_FEDERATE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FEDERATE)
render = _FEDERATE.render

ROLE = PROJECT_ROOT / "roles/web-app-prometheus"
METRICZ = ROLE / "files/nginx/metricz.conf"
LOCATIONS = ROLE / "templates/nginx/locations.conf.j2"
PROMETHEUS_CONFIG = ROLE / "templates/configuration/prometheus.yml.j2"
SECRETS = ROLE / ROLE_FILE_META_SECRETS
SECRET = "ab" * 32
HARNESS = """
local status = "passed"
ngx = {
  HTTP_UNAUTHORIZED = 401,
  var = {http_authorization = arg[2] ~= "" and arg[2] or nil, metricz_bearer_sha256 = arg[3]},
  exit = function(code) error({status = code}) end,
}
package.preload["resty.sha256"] = function()
  return {new = function()
    local seen = ""
    return {update = function(_, text) seen = seen .. text end, final = function() return seen end}
  end}
end
package.preload["resty.string"] = function()
  return {to_hex = function(text) return text end}
end
local ok, err = pcall(dofile, arg[1])
if not ok then status = type(err) == "table" and tostring(err.status) or ("error " .. tostring(err)) end
print(status)
"""


def access_block(text):
    """Args:
    text: an nginx location holding one ``access_by_lua_block``.

    Returns:
        The Lua source of that block.
    """
    found = re.search(
        r"access_by_lua_block \{\n(?P<lua>.*?)\n    \}\n", text, re.DOTALL
    )
    assert found is not None, text
    return found["lua"]


def run_access(lua, header, digest):
    """Args:
    lua: the Lua source of an ``access_by_lua_block``.
    header: the ``Authorization`` header the caller sends, empty for none.
    digest: ``$metricz_bearer_sha256`` of the vhost.

    Returns:
        ``passed`` when the block lets the request through, else the status
        it ends the request with. ``resty.sha256`` is stubbed as the
        identity, so ``digest`` stands for the bearer's own hash.
    """
    with tempfile.TemporaryDirectory() as scratch:
        block = Path(scratch, "block.lua")
        block.write_text(lua, encoding="utf-8")
        harness = Path(scratch, "harness.lua")
        harness.write_text(HARNESS, encoding="utf-8")
        result = subprocess.run(
            ["luajit", str(harness), str(block), header, digest],
            capture_output=True,
            text=True,
            check=True,
        )
    return result.stdout.strip()


@unittest.skipUnless(shutil.which("luajit"), "luajit runs the access blocks")
class MetriczBearerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.lua = access_block(read_text(str(METRICZ)))

    def test_an_outside_request_without_a_bearer_gets_401(self):
        self.assertEqual(run_access(self.lua, "", SECRET), "401")

    def test_a_wrong_bearer_gets_401(self):
        self.assertEqual(run_access(self.lua, f"Bearer {'x' * 64}", SECRET), "401")
        self.assertEqual(run_access(self.lua, f"Basic {SECRET}", SECRET), "401")

    def test_the_scrape_bearer_passes(self):
        self.assertEqual(run_access(self.lua, f"Bearer {SECRET}", SECRET), "passed")

    def test_a_vhost_without_a_digest_refuses_everyone(self):
        self.assertEqual(run_access(self.lua, "Bearer ", ""), "401")
        self.assertEqual(run_access(self.lua, f"Bearer {SECRET}", ""), "401")


@unittest.skipUnless(shutil.which("luajit"), "luajit runs the access blocks")
class FederateBearerRuntimeTests(unittest.TestCase):
    def federate_lua(self, digest_file):
        lua = access_block(render())
        return lua.replace("/etc/nginx/conf.d/federate.sha256", str(digest_file))

    def test_a_missing_digest_file_refuses_every_bearer(self):
        with tempfile.TemporaryDirectory() as scratch:
            lua = self.federate_lua(Path(scratch, "federate.sha256"))
            self.assertEqual(run_access(lua, f"Bearer {SECRET}", ""), "401")

    def test_only_the_bearer_of_the_digest_file_passes(self):
        with tempfile.TemporaryDirectory() as scratch:
            digest = Path(scratch, "federate.sha256")
            other = "cd" * 32
            digest.write_text(f"target {SECRET}\nworker {other}\n", encoding="utf-8")
            lua = self.federate_lua(digest)
            self.assertEqual(run_access(lua, f"Bearer {SECRET}", ""), "passed")
            self.assertEqual(run_access(lua, f"Bearer {other}", ""), "passed")
            self.assertEqual(run_access(lua, f"Bearer {'x' * 64}", ""), "401")
            self.assertEqual(run_access(lua, "", ""), "401")
            digest.write_text(f"worker {other}\n", encoding="utf-8")
            self.assertEqual(run_access(lua, f"Bearer {SECRET}", ""), "401")
            digest.write_text(f"{SECRET}\n", encoding="utf-8")
            self.assertEqual(run_access(lua, f"Bearer {SECRET}", ""), "401")


class MetriczBearerWiringTests(unittest.TestCase):
    def test_the_vhost_sets_the_digest_of_the_credential_before_the_location(self):
        text = read_text(str(LOCATIONS))
        setter = (
            "set $metricz_bearer_sha256 \"{{ lookup('config', 'web-app-prometheus', "
            "'secrets.credentials.metricz_bearer') | hash('sha256') }}\";"
        )
        self.assertIn(setter, text)
        self.assertLess(
            text.index(setter),
            text.index(
                "{% include 'roles/web-app-prometheus/files/nginx/metricz.conf' %}"
            ),
        )

    def test_the_own_scrape_job_presents_the_same_credential(self):
        text = read_text(str(PROMETHEUS_CONFIG))
        job = text[text.index('- job_name: "nginx-metricz"') :]
        job = job[: job.index("- job_name:", 1)]
        self.assertIn("type: Bearer", job)
        self.assertIn(
            "credentials: \"{{ lookup('config', application_id, "
            "'secrets.credentials.metricz_bearer') }}\"",
            job,
        )

    def test_the_credential_is_generated_per_instance(self):
        credential = load_yaml_str(read_text(str(SECRETS)))["credentials"][
            "metricz_bearer"
        ]
        self.assertEqual(credential["algorithm"], "alphanumeric")
        self.assertNotIn("default", credential)


if __name__ == "__main__":
    unittest.main()
