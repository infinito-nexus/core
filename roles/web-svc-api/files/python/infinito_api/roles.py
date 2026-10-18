"""Role data, categories and bundles of a commit, parsed as plain YAML data."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import PurePosixPath

import yaml

ROLE_FILE = re.compile(
    r"^roles/(?P<role>[^/]+)/(?P<file>meta/[^/]+\.ya?ml|vars/main\.yml|README\.md)$"
)
HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
CATEGORY_FILES = ("meta/categories.yml", "roles/categories.yml")
CATEGORY_METADATA = frozenset(
    {"title", "description", "icon", "invokable", "modes", "hanzi", "stage"}
)
BUNDLE_FILE = re.compile(
    r"^inventories/bundles/(?P<target>[^/]+)/(?P<slug>[^/]+)/inventory\.yml$"
)


def parse_yaml(content: bytes):
    """Return the YAML document in ``content``, ``None`` when it does not parse.

    Args:
        content: raw file content.
    """
    try:
        return yaml.safe_load(
            content.decode("utf-8")
        )  # nocheck: direct-yaml  the image carries no core utils; blobs of untrusted refs go through the safe loader only
    except (UnicodeDecodeError, yaml.YAMLError):
        return None


def mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def strings(value) -> list[str]:
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def readme_title(readme: str | None) -> str | None:
    match = HEADING.search(readme or "")
    return match.group(1) if match else None


def category_nodes(tree: dict, path: tuple[str, ...] = ()):
    for key, node in tree.items():
        if key in CATEGORY_METADATA or not isinstance(node, dict):
            continue
        yield (*path, key), node
        yield from category_nodes(node, (*path, key))


def covers(path: tuple[str, ...], role: str) -> bool:
    prefix = "-".join(path)
    return role == prefix or role.startswith(f"{prefix}-")


class RoleData:
    """Readers for the role data of a commit.

    Args:
        repository: the ``Repository`` to read from.
    """

    def __init__(self, repository):
        self.repository = repository

    @lru_cache(maxsize=32)  # noqa: B019  the readers live as long as the process
    def roles(self, commit: str) -> dict[str, dict]:
        paths = [
            p for p in self.repository.paths(commit, "roles") if ROLE_FILE.match(p)
        ]
        roles: dict[str, dict] = {}
        for path, content in self.repository.blobs(commit, paths).items():
            match = ROLE_FILE.match(path)
            entry = roles.setdefault(
                match["role"], {"meta": {}, "vars": None, "readme": None}
            )
            file = match["file"]
            if file.startswith("meta/"):
                entry["meta"][PurePosixPath(file).stem] = parse_yaml(content)
            elif file.startswith("vars/"):
                entry["vars"] = parse_yaml(content)
            else:
                entry["readme"] = content.decode("utf-8", "replace")
        return {
            role: entry
            for role, entry in sorted(roles.items())
            if "main" in entry["meta"]
        }

    @lru_cache(maxsize=32)  # noqa: B019  the readers live as long as the process
    def category_tree(self, commit: str) -> dict:
        blobs = self.repository.blobs(commit, list(CATEGORY_FILES))
        for name in CATEGORY_FILES:
            if name in blobs:
                data = mapping(parse_yaml(blobs[name]))
                return mapping(data.get("roles", data))
        return {}

    def summary(self, commit: str, role: str, translator) -> dict:
        entry = self.roles(commit)[role]
        main = mapping(entry["meta"].get("main"))
        info = mapping(main.get("galaxy_info"))
        services = mapping(entry["meta"].get("services"))
        nodes = [
            (path, node)
            for path, node in category_nodes(self.category_tree(commit))
            if covers(path, role)
        ]
        description = text(info.get("description"))
        return {
            "id": role,
            "application_id": mapping(entry["vars"]).get("application_id"),
            "title": readme_title(entry["readme"]),
            "description": translator.text(f"role:{role}:description", description),
            "categories": [".".join(path) for path, _ in nodes],
            "invokable": any(node.get("invokable") is True for _, node in nodes),
            "lifecycle": next(
                (
                    service["lifecycle"]
                    for service in services.values()
                    if isinstance(service, dict)
                    and isinstance(service.get("lifecycle"), str)
                ),
                None,
            ),
            "logo": mapping(mapping(entry["meta"].get("info")).get("logo")).get(
                "class"
            ),
            "tags": strings(info.get("galaxy_tags")),
        }

    def detail(self, commit: str, role: str, translator) -> dict:
        entry = self.roles(commit)[role]
        return {
            **self.summary(commit, role, translator),
            "meta": entry["meta"],
            "vars": entry["vars"],
        }

    def categories(self, commit: str, translator) -> list[dict]:
        def build(tree: dict, path: tuple[str, ...]) -> list[dict]:
            items = []
            for key, node in tree.items():
                if key in CATEGORY_METADATA or not isinstance(node, dict):
                    continue
                current = (*path, key)
                dotted = ".".join(current)
                items.append(
                    {
                        "id": dotted,
                        "role_prefix": "-".join(current),
                        "title": translator.text(
                            f"category:{dotted}:title", text(node.get("title"))
                        ),
                        "description": translator.text(
                            f"category:{dotted}:description",
                            text(node.get("description")),
                        ),
                        "icon": node.get("icon")
                        if isinstance(node.get("icon"), str)
                        else None,
                        "invokable": node.get("invokable") is True,
                        "children": build(node, current),
                    }
                )
            return items

        return build(self.category_tree(commit), ())

    @lru_cache(maxsize=32)  # noqa: B019  the readers live as long as the process
    def bundles(self, commit: str) -> list[dict]:
        paths = [
            p
            for p in self.repository.paths(commit, "inventories/bundles")
            if BUNDLE_FILE.match(p)
        ]
        result = []
        for path, content in sorted(self.repository.blobs(commit, paths).items()):
            match = BUNDLE_FILE.match(path)
            inventory = mapping(mapping(parse_yaml(content)).get("all"))
            bundle = mapping(
                mapping(mapping(inventory.get("vars")).get("infinito")).get("bundle")
            )
            result.append(
                {
                    "id": f"{match['target']}/{match['slug']}",
                    "deploy_target": match["target"],
                    "slug": match["slug"],
                    "title": text(bundle.get("title")) or None,
                    "description": text(bundle.get("description")) or None,
                    "logo": mapping(bundle.get("logo")).get("class"),
                    "tags": strings(bundle.get("tags")),
                    "categories": strings(bundle.get("categories")),
                    "role_ids": sorted(mapping(inventory.get("children"))),
                }
            )
        return result
