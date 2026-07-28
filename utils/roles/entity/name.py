from utils.roles.categories import (
    categories_file,
    flatten_categories,
    load_categories_tree,
)


def get_entity_name(role_name):
    """
    Get the entity name from a role name by removing the
    longest matching category path from categories.yml.
    """
    categories_tree = load_categories_tree(str(categories_file()))
    all_category_paths = flatten_categories(categories_tree)

    role_name_lc = role_name.lower()
    all_category_paths = [cat.lower() for cat in all_category_paths]
    empty_match = False
    for cat in sorted(all_category_paths, key=len, reverse=True):
        if role_name_lc.startswith(cat + "-"):
            return role_name[len(cat) + 1 :]
        if role_name_lc == cat:
            empty_match = True
    return "" if empty_match else role_name
