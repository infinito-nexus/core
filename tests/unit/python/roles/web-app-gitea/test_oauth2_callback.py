from __future__ import annotations

import configparser
import re
import shutil
import subprocess
import unittest
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.lookup.redirect_uris import build_redirect_uris
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

APP = "web-app-gitea"
ROLE_DIR = PROJECT_ROOT / "roles" / APP
DOMAIN = "code.example.org"
STALE_ROOT_URL = "https://git.example.net/"
LEGACY_SOURCE_NAME = "SSO Login (INFINITO.NEXUS)"
PROVIDER_COLUMN_WIDTH = 25
GO_PATH_SEGMENT_SAFE = "$&+:=@"
JAVA_URI = re.compile(r"(?:[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=]|%[0-9A-Fa-f]{2})+")
AWK_LOOKUP = re.compile(r"awk -F '(?P<sep>[^']+)' '(?P<program>[^']+)'")
PLACEHOLDER = "x"


def source_name() -> str:
    return load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))[
        "GITEA_OIDC_SOURCE_NAME"
    ]


def render_env() -> dict[str, str]:
    """Render the role's env.j2 for an SSO-enabled Gitea served on ``DOMAIN``.

    Returns:
        The rendered KEY=VALUE pairs.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    config = {
        "services.gitea.ports.public.ssh": 2201,
        "services.gitea.configuration.repository.enable_push_create_user": True,
        "services.gitea.configuration.repository.default_private": "last",
        "services.gitea.configuration.repository.default_push_create_private": True,
        "services.prometheus.native_metrics.enabled": False,
    }

    def lookup(name: str, *terms):
        if name == "domain":
            return DOMAIN
        if name == "tls" and terms[1:] == ("url.base",):
            return f"https://{DOMAIN}/"
        if name == "design":
            return {"title": ""}
        if name == "database":
            return PLACEHOLDER
        if name == "objstore":
            return False
        if name == "email":
            return {"enabled": False}
        if name == "config":
            return config[terms[1]]
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["bool"] = bool
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        ENVIRONMENT="production",
        MODE_DEBUG=False,
        GITEA_REDIS_ENABLED=False,
        GITEA_DESIGN_ENABLED=False,
        GITEA_THEMES={"auto": "corporate-auto"},
        GITEA_THEMES_OFFERED=[],
        GITEA_OIDC_ENABLED=True,
        GITEA_LDAP_ENABLED=False,
        GITEA_IAM_ENABLED=True,
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


def restart_long_lived(env: dict[str, str], root_url: str) -> str:
    """Start the pinned image on an app.ini written by an earlier deploy.

    Args:
        env: the container environment.
        root_url: the ROOT_URL that app.ini already holds.

    Returns:
        The ROOT_URL Gitea runs with.
    """
    app_ini = configparser.ConfigParser(interpolation=None)
    app_ini.optionxform = str
    app_ini["server"] = {"ROOT_URL": root_url}
    for name, value in env.items():
        if not name.startswith("GITEA__"):
            continue
        section, _, key = name.removeprefix("GITEA__").partition("__")
        if section.lower() == "server":
            app_ini["server"][key] = value
    app_url = app_ini["server"]["ROOT_URL"]
    return app_url if app_url.endswith("/") else app_url + "/"


def gitea_callback(app_url: str, name: str) -> str:
    return f"{app_url}user/oauth2/{quote(name, safe=GO_PATH_SEGMENT_SAFE)}/callback"


def keycloak_accepts(redirect_uri: str, valid_redirects: list[str]) -> bool:
    """Port of Keycloak 26 ``RedirectUtils.matchesRedirects`` for wildcard entries.

    Args:
        redirect_uri: the redirect_uri the client sends.
        valid_redirects: the client's registered redirect URIs.

    Returns:
        Whether Keycloak accepts the redirect_uri.
    """
    if not JAVA_URI.fullmatch(redirect_uri):
        return False
    bare = re.split(r"[?#]", redirect_uri, maxsplit=1)[0]
    for valid in valid_redirects:
        if valid.endswith("*") and "?" not in valid and "#" not in valid:
            prefix = valid[:-1]
            if bare.startswith(prefix) or bare == prefix.rstrip("/"):
                return True
        elif valid == redirect_uri:
            return True
    return False


def registered_redirects() -> list[str]:
    return build_redirect_uris(
        {APP: DOMAIN},
        {APP: {"services": {"sso": {"enabled": True}}}},
        True,
        deployed=[APP],
    )


def setup_lookup() -> tuple[str, str]:
    task = read_text(str(ROLE_DIR / "tasks" / "setup" / "oidc.yml"))
    match = AWK_LOOKUP.search(task)
    if match is None:
        raise AssertionError("tasks/setup/oidc.yml looks the source up without awk")
    return match["sep"], match["program"]


def converge(listing: str, name: str) -> list[str]:
    """Run the setup's source lookup on ``listing`` and apply its add or update.

    Args:
        listing: what ``gitea admin auth list`` prints.
        name: the name the setup gives the source.

    Returns:
        The names of the OAuth2 sources after the setup ran.
    """
    sep, program = setup_lookup()
    found = subprocess.run(
        [shutil.which("awk"), "-F", sep, program],
        input=listing,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    rows = [re.split(r"\t+", line) for line in listing.splitlines()[1:]]
    sources = {row[0]: row[1] for row in rows if row[2] == "OAuth2"}
    if found:
        sources[found] = name
    else:
        sources[str(len(rows) + 1)] = name
    return list(sources.values())


class TestGiteaOAuth2Callback(unittest.TestCase):
    def test_a_long_lived_instance_sends_a_registered_callback(self) -> None:
        app_url = restart_long_lived(render_env(), STALE_ROOT_URL)
        self.assertEqual(app_url, f"https://{DOMAIN}/")
        self.assertTrue(
            keycloak_accepts(
                gitea_callback(app_url, source_name()), registered_redirects()
            ),
            "Keycloak answers 'Invalid parameter: redirect_uri' to a callback outside the client's redirect URIs",
        )

    def test_a_stale_root_url_sends_an_unregistered_callback(self) -> None:
        self.assertFalse(
            keycloak_accepts(
                gitea_callback(STALE_ROOT_URL, source_name()), registered_redirects()
            )
        )

    def test_an_escaped_source_name_stays_inside_the_wildcard(self) -> None:
        callback = gitea_callback(f"https://{DOMAIN}/", LEGACY_SOURCE_NAME)
        self.assertIn("%20", callback)
        self.assertTrue(keycloak_accepts(callback, registered_redirects()))

    def test_the_source_name_fits_the_provider_column(self) -> None:
        self.assertLessEqual(len(source_name()), PROVIDER_COLUMN_WIDTH)
        self.assertGreater(len(LEGACY_SOURCE_NAME), PROVIDER_COLUMN_WIDTH)

    def test_the_openid2_button_stays_off_under_oidc(self) -> None:
        env = render_env()
        self.assertEqual(env["GITEA__openid__ENABLE_OPENID_SIGNIN"], "false")
        self.assertEqual(env["GITEA__openid__ENABLE_OPENID_SIGNUP"], "false")


class TestGiteaAuthSourceConvergence(unittest.TestCase):
    LISTING = (
        "ID\tName\t\t\tType\t\t\tEnabled\n"
        "1\tLDAP (example.org)\tLDAP (via BindDN)\ttrue\n"
        f"2\t{LEGACY_SOURCE_NAME}\tOAuth2\t\t\ttrue\n"
    )

    def test_the_legacy_source_is_renamed_not_duplicated(self) -> None:
        self.assertEqual(converge(self.LISTING, source_name()), [source_name()])

    def test_a_fresh_instance_gets_one_source(self) -> None:
        listing = (
            "ID\tName\tType\tEnabled\n1\tLDAP (example.org)\tLDAP (via BindDN)\ttrue\n"
        )
        self.assertEqual(converge(listing, source_name()), [source_name()])

    def test_a_converged_instance_stays_at_one_source(self) -> None:
        listing = f"ID\tName\tType\tEnabled\n2\t{source_name()}\tOAuth2\ttrue\n"
        self.assertEqual(converge(listing, source_name()), [source_name()])


if __name__ == "__main__":
    unittest.main()
