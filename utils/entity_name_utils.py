import os

from utils.cache.yaml import load_yaml


def load_categories_tree(categories_file):
    return load_yaml(categories_file)["roles"]


def flatten_categories(tree, prefix=""):
    """Flattens nested category tree to all possible category paths."""
    result = []
    for k, v in tree.items():
        current = f"{prefix}-{k}" if prefix else k
        result.append(current)
        if isinstance(v, dict):
            for sk, sv in v.items():
                if isinstance(sv, dict):
                    result.extend(flatten_categories({sk: sv}, current))
    return result


def get_entity_name(role_name):
    """
    Get the entity name from a role name by removing the
    longest matching category path from categories.yml.
    """
    possible_locations = [
        os.path.join(os.getcwd(), "roles", "categories.yml"),
        os.path.join(os.path.dirname(__file__), "..", "roles", "categories.yml"),
        "roles/categories.yml",
    ]
    categories_file = None
    for loc in possible_locations:
        if os.path.exists(loc):
            categories_file = loc
            break
    if not categories_file:
        return role_name

    categories_tree = load_categories_tree(categories_file)
    all_category_paths = flatten_categories(categories_tree)

    role_name_lc = role_name.lower()
    all_category_paths = [cat.lower() for cat in all_category_paths]
    for cat in sorted(all_category_paths, key=len, reverse=True):
        if role_name_lc.startswith(cat + "-"):
            return role_name[len(cat) + 1 :]
        if role_name_lc == cat:
            return ""
    return role_name
