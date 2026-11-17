from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update import source
from utils.update.base import version_key

from . import PROJECT_ROOT

ROLE = "web-app-mattermost"

SERVER_GATED_RELEASES = {
    "mattermost-plugin-gitlab": ("v2.0.0", "v12.0.0"),
    "mattermost-plugin-jira": ("v5.0.0", "v12.0.0"),
}


def _server_ref() -> str:
    services = load_yaml(str(PROJECT_ROOT / "roles" / ROLE / ROLE_FILE_META_SERVICES))
    return str(services["mattermost"]["ref"])


def _entry(addon_id: str) -> source.VersionSourceEntry | None:
    return next(
        (
            entry
            for entry in source.collect_entries(PROJECT_ROOT)
            if entry.role == ROLE and entry.entity == addon_id
        ),
        None,
    )


def _proposed(entry: source.VersionSourceEntry, tags: list[str]) -> list[str]:
    with mock.patch.object(source, "git_ls_remote_tags", return_value=tags):
        return [update.latest for update in source.outdated([entry], PROJECT_ROOT)]


def _next_patch(version: str) -> str:
    prefix = "v" if version.startswith("v") else ""
    parts = version.removeprefix(prefix).split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return prefix + ".".join(parts)


class TestPluginPinsFollowTheServerRef(unittest.TestCase):
    def test_a_release_the_pinned_server_cannot_activate_is_never_proposed(
        self,
    ) -> None:
        server = _server_ref()
        for addon_id, (gated, required) in SERVER_GATED_RELEASES.items():
            with self.subTest(addon=addon_id):
                entry = _entry(addon_id)
                self.assertIsNotNone(
                    entry, f"the version updater must watch {ROLE}/{addon_id}"
                )
                if version_key(server) >= version_key(required):
                    self.assertNotIn(
                        "match",
                        entry.source,
                        f"services.mattermost.ref builds {server}, which satisfies "
                        f"the min_server_version {required.removeprefix('v')} of "
                        f"{addon_id} {gated}; drop the update.match hold in "
                        f"meta/addons/{addon_id}.yml together with the server bump",
                    )
                    continue
                refused = (
                    f"{addon_id} {gated} and later declare min_server_version "
                    f"{required.removeprefix('v')} in their plugin.json and "
                    f"services.mattermost.ref builds {server}, so the server "
                    "refuses to activate them while mmctl plugin enable exits 0"
                )
                self.assertLess(
                    version_key(entry.current),
                    version_key(gated),
                    f"{refused}; the pinned {entry.current} must stay below {gated}",
                )
                hold = str(entry.source.get("match", ""))
                self.assertTrue(
                    hold and entry.current.startswith(hold),
                    f"{refused}; update.match in meta/addons/{addon_id}.yml must "
                    f"hold a prefix the pinned {entry.current} carries, "
                    f"found {hold or 'none'}",
                )
                self.assertEqual(
                    _proposed(entry, [entry.current, gated]),
                    [],
                    f"{refused}; the updater must not propose {gated}",
                )

    def test_a_patch_release_inside_the_held_line_still_moves_the_pin(self) -> None:
        for addon_id in SERVER_GATED_RELEASES:
            with self.subTest(addon=addon_id):
                entry = _entry(addon_id)
                self.assertIsNotNone(
                    entry, f"the version updater must watch {ROLE}/{addon_id}"
                )
                patch = _next_patch(entry.current)
                self.assertEqual(_proposed(entry, [entry.current, patch]), [patch])


if __name__ == "__main__":
    unittest.main()
