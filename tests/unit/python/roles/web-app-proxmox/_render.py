from __future__ import annotations

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles" / "web-app-proxmox"
COMPOSE = read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
DOCKERFILE = read_text(str(ROLE / "templates" / "Dockerfile.j2"))
ENV = read_text(str(ROLE / "templates" / "env.j2"))
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={})
PROXMOX = SERVICES["proxmox"]
LAUNCHER_ID = 10123
KVM_GID = 992
PUBLISHED = '"127.0.0.1:7992:8006"'

_INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:",
    "roles/sys-svc-container/templates/base.yml.j2": "",
    "roles/sys-svc-container/templates/env.j2": "TZ=UTC\n",
}


def _pins(packages: dict) -> str:
    return " ".join(f"{name}={packages[name]}" for name in sorted(packages))


def _published(term) -> str:
    """Args:
        term: a ``container_ports`` term, the list or the dict form.

    Returns:
        The quoted mapping the lookup renders for it: the loopback web UI
        mapping for the list form, ``<ip>:<public>:<internal>`` of the
        role's declared ports for the dict form.
    """
    if not isinstance(term, dict):
        return PUBLISHED
    ports, protocol = PROXMOX["ports"], term["protocol"]
    return f'"{term["ip"]}:{ports["public"][protocol]}:{ports["internal"][protocol]}"'


def _lookup(name: str, *terms, **_kwargs) -> str:
    if name == "template":
        return "build:\n  context: .\n  dockerfile: Dockerfile"
    if name == "container_image":
        return "image: proxmox"
    if name == "compose_only":
        return f"{terms[0]}: {terms[1]}"
    if name == "container_ports":
        return "ports:\n" + "\n".join(f"  - {_published(term)}" for term in terms)
    if name == "container_volumes":
        return "volumes:\n  - proxmox_guest:/var/lib/proxmox-guest"
    if name == "container_networks":
        return "networks:\n  default: {}"
    if name == "file":
        return read_text(str(terms[0]))
    if name == "path_absolute":
        return str(PROJECT_ROOT / terms[0])
    return ""


def _dotenv_quote(value) -> str:
    return f'"{value}"'


def variables(flavor: str) -> dict:
    """Args:
        flavor: ``vm`` or ``container``.

    Returns:
        The role variables the templates read, as the deploy resolves them
        for that flavor.
    """
    vm = flavor == "vm"
    launcher = {**PROXMOX["launcher"]["packages"], **PROXMOX["ve"]["installer"]}
    return {
        "PROXMOX_IS_VM": vm,
        "PROXMOX_BASE_IMAGE": PROXMOX["image"],
        "PROXMOX_BASE_VERSION": PROXMOX["version"],
        "PROXMOX_VE": PROXMOX["ve"],
        "PROXMOX_IMAGE_PINS": _pins(launcher if vm else PROXMOX["ve"]["packages"]),
        "PROXMOX_LAUNCHER_ID": LAUNCHER_ID,
        "PROXMOX_LAUNCHER_SHARE": "/usr/share/proxmox-launcher",
        "PROXMOX_GUEST_DIR": "/var/lib/proxmox-guest",
        "PROXMOX_GUEST_BASE_DIR": "/var/lib/proxmox-guest-base",
        "PROXMOX_KVM_GID": KVM_GID,
        "PROXMOX_CONTAINER": PROXMOX["name"],
        "PROXMOX_GUEST": PROXMOX["guest"],
        "PROXMOX_GUEST_FQDN": f"{PROXMOX['guest']['node']}.example.org",
        "PROXMOX_INTERNAL_PORT": PROXMOX["ports"]["internal"]["http"],
        "PROXMOX_API": PROXMOX["api"],
        "PROXMOX_ISO_URL": f"{PROXMOX['ve']['iso']['mirror']}/{PROXMOX['ve']['iso']['file']}",
        "DOCKER_BIND_HOST": "127.0.0.1",
        "application_id": "web-app-proxmox",
        "lookup": _lookup,
    }


def render(source: str, flavor: str, **overrides) -> str:
    """Args:
        source: template text, such as ``COMPOSE`` or a planted variant of it.
        flavor: ``vm`` or ``container``.
        **overrides: role variables that replace those of :func:`variables`.

    Returns:
        The rendered text, with the shared compose and container includes
        and every lookup but ``file`` and ``path_absolute`` stubbed.
    """
    environment = Environment(
        loader=DictLoader({**_INCLUDES, "main": source}),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        keep_trailing_newline=True,
    )
    environment.filters["dotenv_quote"] = _dotenv_quote
    environment.filters["bool"] = bool
    return environment.get_template("main").render(**(variables(flavor) | overrides))


def service(flavor: str, source: str = COMPOSE, **overrides) -> dict:
    """Args:
        flavor: ``vm`` or ``container``.
        source: compose template text.
        **overrides: role variables that replace those of :func:`variables`.

    Returns:
        The rendered ``proxmox`` compose service.
    """
    return load_yaml_str(render(source, flavor, **overrides))["services"]["proxmox"]


def planted(source: str, old: str, new: str) -> str:
    """Args:
        source: template text.
        old: text that must occur exactly once.
        new: its replacement.

    Returns:
        The planted variant, for a negative control.
    """
    if source.count(old) != 1:
        raise AssertionError(f"the plant {old!r} does not occur exactly once")
    return source.replace(old, new)
