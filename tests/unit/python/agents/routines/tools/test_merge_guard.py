"""Unit test: the merge guard reports the nocheck marker, the task and the when
clause a fixture merge dropped, and names the pins that drift between parents."""

from __future__ import annotations

import unittest

from agents.routines.tools.merge_guard import lost_markers, version_pin_drift

_PARENT_A = """- name: Install nginx
  package:
    name: nginx
  when: ansible_os_family == "Debian"
# nocheck: distro-guard
"""

_PARENT_B = """- name: Restart service
  service:
    name: nginx
    state: restarted
"""

_MERGED = """- name: Restart service
  service:
    name: nginx
    state: restarted
"""


class TestLostMarkers(unittest.TestCase):
    def test_marker_task_and_when_reported(self) -> None:
        lost = lost_markers(_MERGED, _PARENT_A, _PARENT_B)
        self.assertEqual(lost["nocheck"], ["distro-guard"])
        self.assertEqual(lost["tasks"], ["Install nginx"])
        self.assertEqual(lost["when"], ['ansible_os_family == "Debian"'])

    def test_nothing_lost_when_merged_keeps_everything(self) -> None:
        lost = lost_markers(_PARENT_A, _PARENT_A, _PARENT_A)
        self.assertEqual(lost, {"nocheck": [], "tasks": [], "when": []})


class TestVersionPinDrift(unittest.TestCase):
    def test_pip_and_image_drift_named(self) -> None:
        parent_a = "requests==2.28\nimage: nginx:1.21\nflask==2.0\n"
        parent_b = "requests==2.31\nimage: nginx:1.25\nflask==2.0\n"
        self.assertEqual(version_pin_drift(parent_a, parent_b), ["nginx", "requests"])

    def test_no_drift_when_pins_match(self) -> None:
        pins = "requests==2.31\nimage: nginx:1.25\n"
        self.assertEqual(version_pin_drift(pins, pins), [])

    def test_pin_only_in_one_parent_is_not_drift(self) -> None:
        self.assertEqual(version_pin_drift("flask==2.0\n", "requests==2.31\n"), [])


if __name__ == "__main__":
    unittest.main()
