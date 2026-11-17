"""OpenClaw's trusted-proxy header fits the front proxy's header hash.

The OpenClaw vhost sets a header whose name carries the 64 hex character
``sso_proxy_secret``. nginx stores every ``proxy_set_header`` name in one
``proxy_headers_hash`` bucket and refuses the whole config when a name does
not fit ("could not build proxy_headers_hash, you should increase
proxy_headers_hash_bucket_size: 64"), so every reload on that host fails.
"""

from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.manager.value_generator import ValueGenerator
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

ROLE = "roles/web-app-openclaw"
HEADER_TEMPLATE = f"{ROLE}/templates/nginx/trusted_proxy_header.conf.j2"
NGINX_TEMPLATE = "roles/sys-svc-webserver-core/templates/nginx.conf.j2"
SECRET = "sso_proxy_secret"
POINTER = 8
NGINX_DEFAULT_BUCKET = 64
MODES = {"compose": False, "swarm": True}


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["bool"] = bool
    return env


def _secret_spec() -> dict:
    secrets = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_SECRETS))
    return secrets["credentials"][SECRET]


def secret_header(secret: str) -> str:
    """Render OPENCLAW_TRUSTED_PROXY_SECRET_HEADER the way the role's vars do.

    Args:
        secret: the inventory value of ``sso_proxy_secret``.
    """
    variables = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))
    expected = ("config", variables["application_id"], f"secrets.credentials.{SECRET}")

    def lookup(*terms: str) -> str:
        if terms != expected:
            raise AssertionError(f"unexpected lookup: {terms}")
        return secret

    return (
        _environment()
        .from_string(variables["OPENCLAW_TRUSTED_PROXY_SECRET_HEADER"])
        .render(
            OPENCLAW_TRUSTED_PROXY_SECRET_HEADER_PREFIX=variables[
                "OPENCLAW_TRUSTED_PROXY_SECRET_HEADER_PREFIX"
            ],
            application_id=variables["application_id"],
            lookup=lookup,
        )
    )


def header_names(header: str) -> list[str]:
    """Return every header name the rendered location extra sets.

    Args:
        header: the value of OPENCLAW_TRUSTED_PROXY_SECRET_HEADER.
    """
    rendered = (
        _environment()
        .get_template(HEADER_TEMPLATE)
        .render(OPENCLAW_TRUSTED_PROXY_SECRET_HEADER=header)
    )
    return re.findall(r"^\s*proxy_set_header\s+(\S+)\s", rendered, re.MULTILINE)


def bucket_size(swarm: bool) -> int:
    """Return the proxy_headers_hash_bucket_size the rendered nginx.conf sets.

    Args:
        swarm: the value of IS_SWARM_MODE.

    Returns:
        The last value the config sets, nginx's default when it sets none.
    """

    def lookup(kind: str, *terms: str) -> object:
        if kind == "nginx" and terms == ("directories.configuration.http_includes",):
            return ["/etc/openresty/http/"]
        if kind == "nginx":
            return f"/var/lib/openresty/{terms[0]}"
        if kind == "debug":
            return False
        raise AssertionError(f"unexpected lookup: {kind} {terms}")

    rendered = (
        _environment()
        .get_template(NGINX_TEMPLATE)
        .render(
            IS_SWARM_MODE=swarm,
            NETWORK_DOCKER_DNS_NGINX_DIRECTIVE="resolver 192.0.2.53;",
            WEBSERVER_PROXY_WORKER_PROCESSES=1,
            WEBSERVER_PROXY_WORKER_CONNECTIONS=256,
            WEBSERVER_PROXY_WORKER_RLIMIT_NOFILE=512,
            lookup=lookup,
        )
    )
    sizes = re.findall(
        r"^\s*proxy_headers_hash_bucket_size\s+(\d+)\s*;", rendered, re.MULTILINE
    )
    return int(sizes[-1]) if sizes else NGINX_DEFAULT_BUCKET


def fits(name: str, bucket: int) -> bool:
    """Apply ngx_hash_init's per-key check on a 64-bit build.

    Args:
        name: the header name.
        bucket: the proxy_headers_hash_bucket_size in bytes.

    Returns:
        True when the key's value pointer, its name plus two bytes aligned to a
        pointer, and the bucket's end pointer fit into one bucket.
    """
    aligned = -(-(len(name) + 2) // POINTER) * POINTER
    return bucket >= POINTER + aligned + POINTER


class TestTrustedProxyHeader(unittest.TestCase):
    header: str

    @classmethod
    def setUpClass(cls) -> None:
        spec = _secret_spec()
        secret = ValueGenerator().generate_value(spec["algorithm"])
        if not re.fullmatch(spec["validation"], secret):
            raise AssertionError(f"{SECRET} generator breaks its own validation")
        cls.header = secret_header(secret)

    def test_the_vhost_sets_the_secret_header(self):
        self.assertEqual(header_names(self.header), [self.header])

    def test_nginx_default_bucket_rejects_the_secret_header(self):
        self.assertFalse(fits(self.header, NGINX_DEFAULT_BUCKET))

    def test_every_header_the_vhost_sets_fits_the_configured_bucket(self):
        for mode, swarm in MODES.items():
            bucket = bucket_size(swarm)
            for name in header_names(self.header):
                with self.subTest(mode=mode, length=len(name)):
                    self.assertTrue(fits(name, bucket), f"bucket {bucket}")


if __name__ == "__main__":
    unittest.main()
