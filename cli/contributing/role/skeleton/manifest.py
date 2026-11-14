from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from utils.licensing.rights import table
from utils.roles.description import MAX_LENGTH, violations

KINDS = ("container", "static")
CONTAINER = (KINDS[0],)
DATABASES = ("postgres", "mariadb", "none")
LOGINS = ("oidc", "ldap", "none")
FEATURES = ("email", "redis")

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_REPOSITORY = re.compile(r"^[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9._-]+)*$|^[a-z0-9._-]+$")
_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_JINJA = re.compile(r"{{|{%|{#")
_MISSING = object()


@dataclass(frozen=True)
class Field:
    """One manifest field as the ``schema`` subcommand prints it.

    Args:
        name: the manifest key.
        help: one sentence the builder shows next to the input.
        type: ``string`` or ``integer``.
        choices: the allowed values, when the field is a pick list.
        multiple: whether the field takes a list of values.
        default: the value an omitted optional field takes; required
            fields have none.
        kinds: the manifest kinds the field belongs to; a manifest of
            another kind must leave it out.
    """

    name: str
    help: str
    type: str
    choices: tuple[str, ...] | None = None
    multiple: bool = False
    default: Any = _MISSING
    kinds: tuple[str, ...] = KINDS

    def as_json(self) -> dict[str, Any]:
        """Return the field as the JSON object of the ``schema`` output."""
        out: dict[str, Any] = {
            "name": self.name,
            "help": self.help,
            "type": self.type,
            "kinds": list(self.kinds),
        }
        if self.choices is not None:
            out["choices"] = list(self.choices)
        if self.multiple:
            out["multiple"] = True
        if self.default is not _MISSING:
            out["default"] = self.default
        return out

    @property
    def required(self) -> bool:
        return self.default is _MISSING


@dataclass(frozen=True)
class Volume:
    """One container path the role keeps in a named volume.

    Args:
        key: the ``meta/volumes.yml`` key.
        path: the absolute container path.
    """

    key: str
    path: str


@dataclass(frozen=True)
class Manifest:
    """A validated manifest.

    Args:
        name: suffix of ``web-app-cst-<name>``.
        description: ``galaxy_info.description`` of the role.
        license: SPDX id of the software's licence.
        kind: ``container`` or ``static``; the fields below belong to
            ``container`` only and keep their defaults for ``static``.
        homepage: official website of the software.
        repository: the image without its tag.
        version: the image tag.
        port: the HTTP port the container listens on.
        database: ``postgres``, ``mariadb`` or ``none``.
        login: ``oidc``, ``ldap`` or ``none``.
        features: the optional services the role consumes.
        environment: extra container environment, in manifest order.
        volumes: the container paths kept in named volumes.
    """

    name: str
    description: str
    license: str
    kind: str = KINDS[0]
    homepage: str = ""
    repository: str = ""
    version: str = ""
    port: int = 0
    database: str = "none"
    login: str = "none"
    features: tuple[str, ...] = field(default=())
    environment: tuple[tuple[str, str], ...] = field(default=())
    volumes: tuple[Volume, ...] = field(default=())


def fields() -> tuple[Field, ...]:
    """Return every manifest field in the order the builder asks for them."""
    return (
        Field(
            "kind",
            "What the role deploys: a container image, or a static site of the "
            "Infinito.Nexus family that links the brand kit.",
            "string",
            choices=KINDS,
            default=KINDS[0],
        ),
        Field(
            "name",
            "Short name of the application; the role becomes web-app-cst-<name>. "
            "Lower-case letters, digits and single dashes.",
            "string",
        ),
        Field(
            "description",
            "Noun phrase saying what the software does, at most "
            f"{MAX_LENGTH} characters, not starting with a verb, no trailing period.",
            "string",
        ),
        Field(
            "homepage",
            "Official website of the software (http or https URL).",
            "string",
            kinds=CONTAINER,
        ),
        Field(
            "license",
            "SPDX id of the licence the software is published under.",
            "string",
            choices=tuple(sorted(table())),
        ),
        Field(
            "image",
            "Container image including its tag, e.g. ghcr.io/example/app:1.2.3.",
            "string",
            kinds=CONTAINER,
        ),
        Field(
            "port",
            "HTTP port the container listens on (1 to 65535).",
            "integer",
            kinds=CONTAINER,
        ),
        Field(
            "database",
            "Relational database the application stores its data in.",
            "string",
            choices=DATABASES,
            default="none",
            kinds=CONTAINER,
        ),
        Field(
            "login",
            "How users sign in: OpenID Connect through Keycloak, the central LDAP "
            "directory, or no central login.",
            "string",
            choices=LOGINS,
            default="none",
            kinds=CONTAINER,
        ),
        Field(
            "features",
            "Optional services the application uses.",
            "string",
            choices=FEATURES,
            multiple=True,
            default=[],
            kinds=CONTAINER,
        ),
        Field(
            "environment",
            "Extra container environment variables as KEY=value entries; KEY is "
            "upper-case letters, digits and underscores.",
            "string",
            multiple=True,
            default=[],
            kinds=CONTAINER,
        ),
        Field(
            "volumes",
            "Absolute container paths whose data must survive a redeploy; each "
            "becomes a backed-up named volume.",
            "string",
            multiple=True,
            default=[],
            kinds=CONTAINER,
        ),
    )


def _string(data: dict[str, Any], key: str, errors: list[str]) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key}: must be a non-empty string")
        return ""
    if "\n" in value or "\r" in value:
        errors.append(f"{key}: must be a single line")
    if _JINJA.search(value):
        errors.append(f"{key}: must not contain Jinja delimiters")
    return value.strip()


def _name(data: dict[str, Any], errors: list[str]) -> str:
    value = data.get("name")
    if not isinstance(value, str) or not _NAME.match(value):
        errors.append(
            "name: must consist of [a-z0-9-] only, start and end with a letter "
            f"or digit and hold no double dash, got {value!r}"
        )
        return ""
    return value


def _description(data: dict[str, Any], errors: list[str]) -> str:
    value = _string(data, "description", errors)
    errors.extend(f"description: {problem}" for problem in violations(value))
    return value


def _homepage(data: dict[str, Any], errors: list[str]) -> str:
    value = _string(data, "homepage", errors)
    parts = urlsplit(value)
    if value and (parts.scheme not in ("http", "https") or not parts.netloc):
        errors.append(f"homepage: must be an http or https URL, got {value!r}")
    return value


def _license(data: dict[str, Any], errors: list[str]) -> str:
    value = data.get("license")
    if value not in table():
        errors.append(
            f"license: {value!r} is no SPDX id of meta/licenses.yml; run the schema "
            "subcommand for the choices"
        )
        return ""
    return value


def _image(data: dict[str, Any], errors: list[str]) -> tuple[str, str]:
    value = data.get("image")
    if not isinstance(value, str):
        errors.append("image: must be a string such as ghcr.io/example/app:1.2.3")
        return "", ""
    head, slash, last = value.rpartition("/")
    repository_tail, colon, tag = last.partition(":")
    repository = f"{head}{slash}{repository_tail}"
    if not colon or not _TAG.match(tag):
        errors.append(f"image: {value!r} carries no tag, e.g. {value}:1.2.3")
        return "", ""
    if "@" in value or not _REPOSITORY.match(repository):
        errors.append(f"image: {value!r} is no valid image reference")
        return "", ""
    return repository, tag


def _port(data: dict[str, Any], errors: list[str]) -> int:
    value = data.get("port")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        errors.append(f"port: must be an integer from 1 to 65535, got {value!r}")
        return 0
    return value


def _choice(
    data: dict[str, Any],
    key: str,
    choices: tuple[str, ...],
    errors: list[str],
    default: str = "none",
) -> str:
    value = data.get(key, default)
    if value not in choices:
        errors.append(f"{key}: must be one of {', '.join(choices)}, got {value!r}")
        return default
    return value


def _features(data: dict[str, Any], errors: list[str]) -> tuple[str, ...]:
    value = data.get("features", [])
    if not isinstance(value, list):
        errors.append(f"features: must be a list of {', '.join(FEATURES)}")
        return ()
    unknown = [item for item in value if item not in FEATURES]
    errors.extend(
        f"features: {item!r} is not one of {', '.join(FEATURES)}" for item in unknown
    )
    return tuple(item for item in FEATURES if item in value)


def _environment_items(value: Any, errors: list[str]) -> list[tuple[Any, Any]]:
    if isinstance(value, dict):
        return list(value.items())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = [tuple(item.split("=", 1)) for item in value]
        bad = [item[0] for item in items if len(item) != 2]
        errors.extend(f"environment: {entry!r} is no KEY=value entry" for entry in bad)
        return [item for item in items if len(item) == 2]
    errors.append("environment: must be a mapping or a list of KEY=value entries")
    return []


def _environment(
    data: dict[str, Any], errors: list[str]
) -> tuple[tuple[str, str], ...]:
    out: dict[str, str] = {}
    for key, value in _environment_items(data.get("environment", {}), errors):
        if not isinstance(key, str) or not _ENV_KEY.match(key):
            errors.append(f"environment: key {key!r} must match [A-Z_][A-Z0-9_]*")
            continue
        if not isinstance(value, (str, int, float)):
            errors.append(f"environment: {key} must be a string or number")
            continue
        text = str(value).lower() if isinstance(value, bool) else str(value)
        if "\n" in text or "\r" in text:
            errors.append(f"environment: {key} must be a single line")
            continue
        if key in out:
            errors.append(f"environment: {key} is given twice")
            continue
        out[key] = text
    return tuple(out.items())


def _volumes(data: dict[str, Any], errors: list[str]) -> tuple[Volume, ...]:
    value = data.get("volumes", [])
    if not isinstance(value, list):
        errors.append("volumes: must be a list of absolute container paths")
        return ()
    out: dict[str, Volume] = {}
    for item in value:
        path = PurePosixPath(item) if isinstance(item, str) else None
        if (
            path is None
            or not path.is_absolute()
            or path == PurePosixPath("/")
            or ".." in path.parts  # nocheck: project-root-import  container path
            or any(char in item for char in ":\n\r\t ")
        ):
            errors.append(f"volumes: {item!r} must be an absolute container path")
            continue
        key = re.sub(r"[^a-z0-9]+", "_", str(path).lower()).strip("_")
        if key in out:
            errors.append(
                f"volumes: {item!r} maps onto the same volume as {out[key].path!r}"
            )
            continue
        out[key] = Volume(key=key, path=str(path))
    return tuple(out.values())


def _scope(data: dict[str, Any], errors: list[str]) -> tuple[str, dict[str, Any]]:
    known = {item.name: item for item in fields()}
    errors.extend(f"{key}: unknown field" for key in data if key not in known)
    kind = _choice(data, "kind", KINDS, errors, KINDS[0])
    errors.extend(
        f"{key}: only for kind {', '.join(known[key].kinds)}"
        for key in data
        if key in known and kind not in known[key].kinds
    )
    errors.extend(
        f"{item.name}: required"
        for item in known.values()
        if kind in item.kinds and item.required and item.name not in data
    )
    return kind, {
        key: value
        for key, value in data.items()
        if key in known and kind in known[key].kinds
    }


def validate(data: Any) -> tuple[Manifest | None, list[str]]:
    """Validate a parsed manifest.

    Args:
        data: the manifest as parsed from JSON or YAML.

    Returns:
        The manifest and an empty list, or ``None`` and one ``<field>: <problem>``
        line per error.
    """
    if not isinstance(data, dict):
        return None, ["manifest: must be a mapping of the fields the schema lists"]
    errors: list[str] = []
    kind, scoped = _scope(data, errors)
    homepage = _homepage(scoped, errors) if "homepage" in scoped else ""
    repository, version = _image(scoped, errors) if "image" in scoped else ("", "")
    manifest = Manifest(
        name=_name(scoped, errors) if "name" in scoped else "",
        description=_description(scoped, errors) if "description" in scoped else "",
        license=_license(scoped, errors) if "license" in scoped else "",
        kind=kind,
        homepage=homepage,
        repository=repository,
        version=version,
        port=_port(scoped, errors) if "port" in scoped else 0,
        database=_choice(scoped, "database", DATABASES, errors),
        login=_choice(scoped, "login", LOGINS, errors),
        features=_features(scoped, errors),
        environment=_environment(scoped, errors),
        volumes=_volumes(scoped, errors),
    )
    if manifest.login == "oidc" and homepage and urlsplit(homepage).scheme != "https":
        errors.append(
            "homepage: must be an https URL for login oidc, "
            "since meta/account.yml cites it as the account policy source"
        )
    return (None, errors) if errors else (manifest, [])
