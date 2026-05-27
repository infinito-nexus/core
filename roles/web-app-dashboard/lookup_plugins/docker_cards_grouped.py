from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        """
        Group the given cards into categorized and uncategorized lists
        based on the tags from menu_categories.
        Categories are sorted alphabetically before returning.
        """
        if len(terms) < 2:
            raise AnsibleError("Missing required arguments")

        cards = terms[0]
        menu_categories = terms[1]

        categorized = {}
        uncategorized = []

        # Categorize cards
        for card in cards:
            found = False
            for category, data in menu_categories.items():
                if any(tag in data.get("tags", []) for tag in card.get("tags", [])):
                    categorized.setdefault(category, []).append(card)
                    found = True
                    break
            if not found:
                uncategorized.append(card)

        # Sort categories alphabetically
        sorted_categorized = {
            k: categorized[k] for k in sorted(categorized.keys(), key=str.lower)
        }

        return [
            {
                "categorized": sorted_categorized,
                "uncategorized": uncategorized,
            }
        ]
