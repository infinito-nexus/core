import re

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


def slugify(name):
    """Return the URL segment of a folder name.

    Args:
        name: the folder name as written in ``menu_categories.yml``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise AnsibleError(f"Folder {name!r} has no URL-safe characters")
    return slug


def _check_unique_names(folders, seen):
    for name, entry in folders.items():
        if ("name", name) in seen:
            raise AnsibleError(f"Folder name {name!r} appears twice in the tree")
        slug = slugify(name)
        if ("slug", slug) in seen:
            raise AnsibleError(f"Folder name {name!r} repeats the URL segment {slug!r}")
        seen.update((("name", name), ("slug", slug)))
        _check_unique_names(entry.get("children") or {}, seen)


def _matches(entry, card):
    return bool(set(entry.get("tags") or []) & set(card.get("tags") or []))


def _place(folders, cards, parent, placed):
    nodes = []
    for name, entry in folders.items():
        path = f"{parent}/{slugify(name)}" if parent else slugify(name)
        node = {
            "name": name,
            "path": path,
            "slug": slugify(name),
            "description": entry["description"],
            "icon": entry["icon"],
            "fallback": bool(entry.get("fallback")),
            "cards": [card for card in cards if _matches(entry, card)],
            "children": _place(entry.get("children") or {}, cards, path, placed),
        }
        for card in node["cards"]:
            placed.setdefault(card["id"], []).append(path)
        nodes.append(node)
    return nodes


def _fill_fallback(nodes, cards, placed):
    for node in nodes:
        if node["fallback"]:
            node["cards"] = [card for card in cards if card["id"] not in placed]
            for card in node["cards"]:
                placed.setdefault(card["id"], []).append(node["path"])
        _fill_fallback(node["children"], cards, placed)


def _prune(nodes):
    kept = []
    for node in nodes:
        node["children"] = _prune(node["children"])
        if node["cards"] or node["children"]:
            kept.append(node)
    return kept


def _folder_view(nodes):
    return [
        {
            "slug": node["slug"],
            "name": node["name"],
            "description": node["description"],
            "icon": {"class": node["icon"]},
            "children": _folder_view(node["children"]),
        }
        for node in nodes
    ]


def _menu_view(nodes):
    return [
        {
            "name": node["name"],
            "description": node["description"],
            "icon": {"class": node["icon"]},
            "children": _menu_view(node["children"])
            + [
                {
                    "name": card["title"],
                    "description": card["text"],
                    "icon": card["icon"],
                    "url": card["url"],
                    "iframe": card["iframe"],
                }
                for card in node["cards"]
            ],
        }
        for node in nodes
    ]


def group(cards, folders):
    """Place every card into each folder whose tags it shares.

    Args:
        cards: output of the ``docker_cards`` lookup; every card has ``id`` and ``tags``.
        folders: ``portfolio_menu_categories``; a folder holds ``description``,
            ``icon`` and optionally ``tags``, ``children`` and ``fallback``. A
            ``fallback`` folder receives every card no other folder takes.

    Returns:
        ``{"cards": [...], "folders": [...], "menu": [...]}``: the cards with
        their ``folders`` slug paths, the folder tree for port-ui's folder view
        and the same tree as navigation entries for the Apps menu; folders
        without a card in their subtree are left out of both trees.
    """
    _check_unique_names(folders, set())
    placed = {}
    nodes = _place(folders, cards, "", placed)
    _fill_fallback(nodes, cards, placed)
    nodes = _prune(nodes)
    return {
        "cards": [{**card, "folders": placed.get(card["id"], [])} for card in cards],
        "folders": _folder_view(nodes),
        "menu": _menu_view(nodes),
    }


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if len(terms) < 2:
            raise AnsibleError("docker_cards_grouped needs the cards and the folders")
        return [group(terms[0], terms[1])]
