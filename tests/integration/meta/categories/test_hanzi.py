import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.categories import categories_file

ATTRIBUTE_KEYS = frozenset(
    {
        "bootstrap",
        "description",
        "hanzi",
        "icon",
        "invokable",
        "modes",
        "run_after",
        "stage",
        "title",
    }
)


def _categories(node, path=()):
    """Yield ``(path, attrs)`` for every category node below *node*.

    Args:
        node: mapping of category keys to their attribute mappings.
        path: category keys already walked, joined into the role prefix.
    """
    for key, value in node.items():
        if key in ATTRIBUTE_KEYS or not isinstance(value, dict):
            continue
        yield (*path, key), value
        yield from _categories(value, (*path, key))


class TestCategoryHanzi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = load_yaml_any(str(categories_file()))
        cls.categories = list(_categories(data["roles"]))

    def test_every_category_declares_a_hanzi(self):
        missing = sorted(
            "-".join(path) for path, attrs in self.categories if not attrs.get("hanzi")
        )
        self.assertEqual([], missing, f"Categories without a hanzi label: {missing}")

    def test_hanzi_is_unique_among_siblings(self):
        """Sibling scope, not tree scope: the labels are path fragments and
        repeat across branches on purpose (web-svc and svc both carry 服务)."""
        seen = {}
        collisions = []

        for path, attrs in self.categories:
            key = (path[:-1], attrs.get("hanzi"))
            name = "-".join(path)
            if key in seen:
                collisions.append(f"{attrs.get('hanzi')}: {seen[key]} vs {name}")
            seen[key] = name

        self.assertEqual([], collisions, f"Duplicate hanzi labels: {collisions}")


if __name__ == "__main__":
    unittest.main()
