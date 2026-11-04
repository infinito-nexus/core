import sys
import unittest

from ansible.errors import AnsibleError

from utils.cache.files import PROJECT_ROOT

sys.path.insert(
    0,
    str(PROJECT_ROOT / "roles" / "web-app-dashboard" / "lookup_plugins"),
)

from docker_cards_grouped import LookupModule, group, slugify


def _card(card_id, *tags):
    return {
        "id": card_id,
        "title": card_id.title(),
        "text": f"{card_id} text",
        "icon": {"class": "fa-solid fa-cube"},
        "url": f"https://{card_id}.example",
        "iframe": True,
        "tags": list(tags),
    }


FOLDERS = {
    "Communication & Collaboration": {
        "description": "Talk",
        "icon": "fa-solid fa-comments",
        "children": {
            "Mail": {"description": "Mail", "icon": "i-mail", "tags": ["mail"]},
            "Chat": {"description": "Chat", "icon": "i-chat", "tags": ["chat"]},
        },
    },
    "Business": {
        "description": "Money",
        "icon": "fa-solid fa-briefcase",
        "children": {
            "Marketing": {
                "description": "Reach",
                "icon": "i-marketing",
                "tags": ["newsletter"],
            },
        },
    },
    "Community": {
        "description": "People",
        "icon": "i-community",
        "tags": ["newsletter", "forum"],
    },
    "Other": {"description": "Rest", "icon": "i-other", "fallback": True},
}


class TestGroup(unittest.TestCase):
    def test_a_card_lands_in_every_folder_whose_tags_it_shares(self):
        result = group([_card("listmonk", "newsletter")], FOLDERS)

        self.assertEqual(
            result["cards"][0]["folders"], ["business/marketing", "community"]
        )

    def test_nested_paths_join_the_slugs_of_every_level(self):
        result = group([_card("mailu", "mail")], FOLDERS)

        self.assertEqual(
            result["cards"][0]["folders"], ["communication-collaboration/mail"]
        )

    def test_a_card_without_a_matching_tag_falls_into_the_fallback_folder(self):
        result = group([_card("chess", "game")], FOLDERS)

        self.assertEqual(result["cards"][0]["folders"], ["other"])

    def test_the_fallback_folder_ignores_cards_other_folders_took(self):
        result = group([_card("mailu", "mail"), _card("chess", "game")], FOLDERS)

        other = next(node for node in result["menu"] if node["name"] == "Other")
        self.assertEqual([entry["name"] for entry in other["children"]], ["Chess"])

    def test_folders_without_a_card_in_their_subtree_are_left_out(self):
        result = group([_card("mailu", "mail")], FOLDERS)

        top = result["folders"]
        self.assertEqual(
            [node["slug"] for node in top], ["communication-collaboration"]
        )
        self.assertEqual([node["slug"] for node in top[0]["children"]], ["mail"])

    def test_the_folder_view_holds_no_tags_and_no_cards(self):
        result = group([_card("mailu", "mail")], FOLDERS)

        self.assertEqual(
            result["folders"][0]["children"][0],
            {
                "slug": "mail",
                "name": "Mail",
                "description": "Mail",
                "icon": {"class": "i-mail"},
                "children": [],
            },
        )

    def test_the_menu_lists_subfolders_before_the_apps_of_a_folder(self):
        cards = [_card("discourse", "forum")]
        folders = {
            "Community": {
                "description": "People",
                "icon": "i-community",
                "tags": ["forum"],
                "children": {
                    "Boards": {"description": "B", "icon": "i-b", "tags": ["forum"]}
                },
            }
        }

        menu = group(cards, folders)["menu"]

        self.assertEqual(
            [entry["name"] for entry in menu[0]["children"]], ["Boards", "Discourse"]
        )
        self.assertEqual(
            menu[0]["children"][1],
            {
                "name": "Discourse",
                "description": "discourse text",
                "icon": {"class": "fa-solid fa-cube"},
                "url": "https://discourse.example",
                "iframe": True,
            },
        )

    def test_a_tag_no_folder_knows_leaves_the_card_out_without_a_fallback(self):
        folders = {"Mail": {"description": "Mail", "icon": "i-mail", "tags": ["mail"]}}

        result = group([_card("chess", "game")], folders)

        self.assertEqual(result["cards"][0]["folders"], [])
        self.assertEqual(result["folders"], [])

    def test_a_folder_name_used_twice_fails(self):
        folders = {
            "A": {
                "description": "A",
                "icon": "i",
                "children": {"Mail": {"description": "M", "icon": "i"}},
            },
            "Mail": {"description": "M", "icon": "i"},
        }

        with self.assertRaises(AnsibleError):
            group([], folders)

    def test_two_names_with_the_same_url_segment_fail(self):
        folders = {
            "Cloud & Office": {"description": "C", "icon": "i"},
            "Cloud Office": {"description": "C", "icon": "i"},
        }

        with self.assertRaisesRegex(AnsibleError, "cloud-office"):
            group([], folders)


class TestSlugify(unittest.TestCase):
    def test_slug_keeps_letters_and_digits_and_joins_the_rest(self):
        self.assertEqual(
            slugify("Communication & Collaboration"), "communication-collaboration"
        )

    def test_a_name_without_url_safe_characters_fails(self):
        with self.assertRaises(AnsibleError):
            slugify("&&")


class TestLookup(unittest.TestCase):
    def test_lookup_returns_the_grouping(self):
        result = LookupModule().run([[_card("mailu", "mail")], FOLDERS])

        self.assertEqual(
            result[0]["cards"][0]["folders"], ["communication-collaboration/mail"]
        )

    def test_lookup_needs_cards_and_folders(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([[]])


if __name__ == "__main__":
    unittest.main()
