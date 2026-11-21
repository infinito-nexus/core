from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path

from jinja2 import BaseLoader, Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml, load_yaml_any, load_yaml_str
from utils.roles.applications.services.registry import load_applications_from_roles_dir
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ENGINE = "svc-ai-libretranslate-engine"
FRONT = "web-svc-libretranslate"
ENGINE_SERVICE = "libretranslate-engine"
FRONT_SERVICE = "libretranslate"
ENGINE_FLAG = f"{{{{ '{ENGINE}' in group_names }}}}"
IMAGE = "libretranslate/libretranslate"
PREFETCH = "prefetch_models.py"
ROLES = Path(PROJECT_ROOT) / "roles"
ENGINE_ENV = ROLES / ENGINE / "templates" / "env.j2"
DOCKERFILES = ("files/Dockerfile", "templates/Dockerfile.j2")
SELECTION = ("load_only", "directions", "model_store", "loading_model", "gpu")
STORE_READS = ("libretranslate_store(", "cache_artefacts")
DESIGN_FLAG = "services.design.enabled"
FRONT_DESIGN_READ = f"LIBRETRANSLATE_ENGINE_FRONT_ID, '{DESIGN_FLAG}'"
RESOLVER = "resolver 127.0.0.11 valid=30s ipv6=off;"
NGINX_VARS = (
    "application_id",
    "LIBRETRANSLATE_PORT",
    "LIBRETRANSLATE_BACKEND_ID",
    "LIBRETRANSLATE_BACKEND_HOST",
    "LIBRETRANSLATE_BACKEND_PORT",
)
UPSTREAM = re.compile(r"^\s*set \$libretranslate_engine (\S+);$", re.MULTILINE)
LISTEN = re.compile(r"^\s*listen (\d+);$", re.MULTILINE)
LOCATIONS = re.compile(r"^\s*location (.+?) \{$", re.MULTILINE)
SELF_ANSWER = re.compile(r"^\s*return\s", re.MULTILINE)
TITLE_LINE = re.compile(r"^LT_FRONTEND_TITLE=.*\n", re.MULTILINE)
TITLE = "LibreTranslate Front"
OLD_HEALTH = '    location = /healthz {\n        return 200 "ok\\n";\n    }\n\n'


class _Stub(BaseLoader):
    def get_source(self, environment, template):
        return "", template, lambda: True


class _Design:
    def __init__(self, title) -> None:
        self.title = title


def _environment() -> Environment:
    return Environment(
        loader=_Stub(),
        undefined=StrictUndefined,
        trim_blocks=True,
        autoescape=select_autoescape(default_for_string=False),
    )


def _services(role: str) -> dict:
    return copy.deepcopy(load_yaml(str(ROLES / role / ROLE_FILE_META_SERVICES)))


def _config(role: str, path: str):
    node = {"services": _services(role)}
    for part in path.split("."):
        node = node[part]
    return node


def _front() -> dict:
    base = ROLES / FRONT
    return {
        "services": _services(FRONT),
        "variants": copy.deepcopy(load_yaml_any(str(base / ROLE_FILE_META_VARIANTS))),
        "vars": read_text(str(base / ROLE_FILE_VARS_MAIN)),
        "compose": read_text(str(base / ROLE_FILE_TEMPL_COMPOSE)),
        "nginx": read_text(str(base / "templates" / "nginx.conf.j2")),
        "dockerfiles": [path for path in DOCKERFILES if (base / path).is_file()],
    }


def _nginx(front: dict) -> str:
    env = _environment()
    env.globals["lookup"] = lambda name, role, path: _config(role, path)
    raw = load_yaml_str(front["vars"])
    values = {"NETWORK_DOCKER_DNS_NGINX_DIRECTIVE": RESOLVER}
    for name in NGINX_VARS:
        values[name] = env.from_string(str(raw[name])).render(values)
    return env.from_string(front["nginx"]).render(values)


def _image_roles(applications: dict) -> set[str]:
    return {
        role
        for role, config in applications.items()
        for service in (config.get("services") or {}).values()
        if isinstance(service, dict) and service.get("image") == IMAGE
    }


def _prefetch_copies() -> list[str]:
    return sorted(
        str(Path(path).relative_to(PROJECT_ROOT))
        for path in iter_project_files(extensions=(PREFETCH,), exclude_tests=True)
        if Path(path).name == PREFETCH
    )


def _engine_pins(front: dict) -> list[dict]:
    return [
        (variant.get("services") or {}).get(ENGINE_SERVICE) or {}
        for variant in front["variants"]
    ]


def _container_findings(front: dict) -> list[str]:
    own = front["services"][FRONT_SERVICE]
    consumed = front["services"].get(ENGINE_SERVICE) or {}
    checks = (
        (
            own.get("image") == IMAGE or own.get("custom"),
            "the front runs a LibreTranslate container",
        ),
        (
            front["dockerfiles"] or "build.yml.j2" in front["compose"],
            "the front builds an image",
        ),
        (any(key in own for key in SELECTION), "the front keeps a model selection"),
        (
            any(read in front["vars"] for read in STORE_READS),
            "the front reads the model store",
        ),
        (
            consumed.get("mandatory") is not True
            or consumed.get("enabled") != ENGINE_FLAG
            or consumed.get("shared") != ENGINE_FLAG,
            "the front does not consume the engine",
        ),
        (
            any(
                pin.get(flag) is not True
                for pin in _engine_pins(front)
                for flag in ("enabled", "shared")
            ),
            "a variant deploys the front without the engine",
        ),
    )
    return [finding for failed, finding in checks if failed]


def _forwarder_findings(front: dict) -> list[str]:
    own = front["services"][FRONT_SERVICE]
    engine = _services(ENGINE)[ENGINE_SERVICE]
    target = f"http://{engine['name']}:{engine['ports']['internal']['http']}"
    port = str(own["ports"]["internal"]["http"])
    sso = front["services"]["sso"]["oauth2"]
    sso_origin = (str(sso["origin"]["host"]), str(sso["origin"]["port"]))
    nginx = _nginx(front)
    checks = (
        (
            UPSTREAM.findall(nginx) != [target]
            or "proxy_pass $libretranslate_engine;" not in nginx,
            "the forwarder does not reach the engine",
        ),
        (
            LISTEN.findall(nginx) != [port] or sso_origin != (FRONT_SERVICE, port),
            "the sso origin and the forwarder disagree",
        ),
        (
            LOCATIONS.findall(nginx) != ["/"] or bool(SELF_ANSWER.search(nginx)),
            "the forwarder answers a request itself instead of the engine",
        ),
        (
            f"/{own['healthcheck']['path']}" not in sso["acl"]["whitelist"],
            "the healthcheck does not probe an engine API path",
        ),
    )
    return [finding for failed, finding in checks if failed]


def _title_findings(template: str, design_enabled: bool, title) -> list[str]:
    asked: list = []
    front_id = load_yaml_str(read_text(str(ROLES / ENGINE / ROLE_FILE_VARS_MAIN)))[
        "LIBRETRANSLATE_ENGINE_FRONT_ID"
    ]

    def lookup(name: str, *terms):
        asked.append((name, terms))
        if name == "config" and terms == (FRONT, DESIGN_FLAG):
            return design_enabled
        if name == "design" and terms == (FRONT,):
            return _Design(title)
        raise LookupError(f"{name}{terms}")

    env = _environment()
    env.filters["bool"] = bool
    env.globals["lookup"] = lookup
    try:
        rendered = env.from_string(template).render(
            application_id=ENGINE,
            LIBRETRANSLATE_ENGINE_LOAD_ONLY="",
            LIBRETRANSLATE_ENGINE_STORED=False,
            LIBRETRANSLATE_ENGINE_THREADS=1,
            LIBRETRANSLATE_ENGINE_FRONT_ID=front_id,
        )
    except LookupError as exc:
        return [f"the engine asks {exc} instead of the front's design"]
    shown = [line for line in rendered.splitlines() if line.startswith("LT_FRONTEND")]
    found = []
    if shown != ([f"LT_FRONTEND_TITLE={title}"] if design_enabled and title else []):
        found.append("the engine does not show the front's title")
    if design_enabled and ("design", (FRONT,)) not in asked:
        found.append("the engine does not ask the front's design")
    return found


class TestLibretranslateFront(unittest.TestCase):
    def test_only_the_engine_runs_a_libretranslate_container(self) -> None:
        self.assertEqual(
            _image_roles(load_applications_from_roles_dir(ROLES)), {ENGINE}
        )

    def test_prefetch_models_exists_once_under_the_engine(self) -> None:
        self.assertEqual(
            _prefetch_copies(), [f"roles/{ENGINE}/files/python/{PREFETCH}"]
        )

    def test_the_front_runs_no_libretranslate_and_builds_nothing(self) -> None:
        self.assertEqual(_container_findings(_front()), [])

    def test_the_front_forwards_every_request_to_the_engine(self) -> None:
        self.assertEqual(_forwarder_findings(_front()), [])

    def test_the_engine_shows_the_front_title_only_with_its_design(self) -> None:
        template = read_text(str(ENGINE_ENV))
        for design_enabled, title in ((True, TITLE), (True, False), (False, TITLE)):
            with self.subTest(design_enabled=design_enabled, title=title):
                self.assertEqual(_title_findings(template, design_enabled, title), [])

    def test_the_guard_reports_a_front_that_runs_libretranslate_again(self) -> None:
        front = _front()
        own = front["services"][FRONT_SERVICE]
        own.update(image=IMAGE, custom=True, load_only=[], model_store=True)
        front["dockerfiles"] = list(DOCKERFILES[:1])
        front["vars"] += "LIBRETRANSLATE_STORE: '{{ x | libretranslate_store() }}'\n"
        front["services"][ENGINE_SERVICE]["mandatory"] = False
        _engine_pins(front)[-1]["enabled"] = False
        self.assertEqual(
            _container_findings(front),
            [
                "the front runs a LibreTranslate container",
                "the front builds an image",
                "the front keeps a model selection",
                "the front reads the model store",
                "the front does not consume the engine",
                "a variant deploys the front without the engine",
            ],
        )
        self.assertEqual(
            _image_roles({FRONT: {"services": {FRONT_SERVICE: own}}}), {FRONT}
        )

    def test_the_guard_reports_a_forwarder_that_misses_the_engine(self) -> None:
        front = _front()
        front["nginx"] = front["nginx"].replace(
            "{{ LIBRETRANSLATE_BACKEND_HOST }}", "{{ application_id }}"
        )
        self.assertEqual(
            _forwarder_findings(front), ["the forwarder does not reach the engine"]
        )

    def test_the_guard_reports_a_health_probe_the_forwarder_answers(self) -> None:
        front = _front()
        front["nginx"] = front["nginx"].replace(
            "    location / {\n", OLD_HEALTH + "    location / {\n"
        )
        front["services"][FRONT_SERVICE]["healthcheck"]["path"] = "healthz"
        self.assertEqual(
            _forwarder_findings(front),
            [
                "the forwarder answers a request itself instead of the engine",
                "the healthcheck does not probe an engine API path",
            ],
        )

    def test_the_guard_reports_an_engine_without_the_front_title(self) -> None:
        template = read_text(str(ENGINE_ENV))
        stripped = TITLE_LINE.sub("", template)
        self.assertNotEqual(stripped, template)
        self.assertEqual(
            _title_findings(stripped, True, TITLE),
            ["the engine does not show the front's title"],
        )

    def test_the_guard_reports_an_engine_reading_its_own_design_flag(self) -> None:
        template = read_text(str(ENGINE_ENV))
        self.assertIn(FRONT_DESIGN_READ, template)
        own_flag = template.replace(
            FRONT_DESIGN_READ, f"application_id, '{DESIGN_FLAG}'"
        )
        asked = f"config{(ENGINE, DESIGN_FLAG)}"
        self.assertEqual(
            _title_findings(own_flag, True, TITLE),
            [f"the engine asks {asked} instead of the front's design"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
