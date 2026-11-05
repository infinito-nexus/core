import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import timing  # noqa: E402

LINES = {i: {"id": i, "text": i} for i in ("a", "b", "c", "d")}
DURS = {"a": 2.0, "b": 1.5, "c": 3.0, "d": 1.0}


class Layout(unittest.TestCase):
    def setUp(self):
        self.t = timing.layout([{"id": "intro", "music": 2.0}, {"id": "s1", "lines": ["a", "b"]}, {"id": "s2", "lines": ["c", "d"]}],
                               LINES, DURS, bpm=120, fps=60)

    def test_lines_inside_a_scene_are_gap_apart(self):
        ln = self.t["lines"]
        self.assertAlmostEqual(ln["b"]["start"] - ln["a"]["end"], timing.GAP)
        self.assertAlmostEqual(ln["d"]["start"] - ln["c"]["end"], timing.GAP)

    def test_scene_change_gap_is_about_scene_gap(self):
        ln = self.t["lines"]
        self.assertAlmostEqual(ln["c"]["start"] - ln["b"]["end"], timing.SCENE_GAP)

    def test_scene_ends_are_on_half_beats(self):
        for s in self.t["scenes"]:
            self.assertAlmostEqual((s["end"] / 0.25) % 1, 0, places=6)

    def test_slot_covers_line_plus_gap_and_last_slot_reaches_scene_end(self):
        ln = self.t["lines"]
        self.assertAlmostEqual(ln["a"]["slot"], ln["b"]["start"])
        self.assertEqual(ln["b"]["slot"], self.t["scenes"][1]["end"])

    def test_durations_follow_the_takes(self):
        ln = self.t["lines"]
        for k, d in DURS.items():
            self.assertAlmostEqual(ln[k]["end"] - ln[k]["start"], d)
        self.assertEqual(self.t["frames"], round(self.t["scenes"][-1]["end"] * 60))

    def test_hold_and_min_lengthen(self):
        lines = {**LINES, "a": {"id": "a", "text": "a", "hold": 1.0}}
        t = timing.layout([{"id": "s1", "lines": ["a", "b"], "min": 20}], lines, DURS, bpm=120, fps=60)
        self.assertAlmostEqual(t["lines"]["b"]["start"] - t["lines"]["a"]["end"], 1.0 + timing.GAP)
        self.assertGreaterEqual(t["scenes"][0]["end"], 20)


class Changes(unittest.TestCase):
    def test_first_change_names_the_first_moved_scene(self):
        scenes = [{"id": "s1", "lines": ["a", "b"]}, {"id": "s2", "lines": ["c", "d"]}]
        old = timing.layout(scenes, LINES, DURS, 120, 60)
        new = timing.layout(scenes, LINES, {**DURS, "c": 3.4}, 120, 60)
        self.assertIsNone(timing.first_change(old, old))
        self.assertEqual(timing.first_change(old, new), "s2")
        self.assertEqual(timing.first_change(None, new), "s1")

    def test_take_key_changes_with_text_and_voice(self):
        k = timing.take_key({"text": "hi"}, {"exaggeration": 0.5}, "chatterbox")
        self.assertNotEqual(k, timing.take_key({"text": "hi!"}, {"exaggeration": 0.5}, "chatterbox"))
        self.assertNotEqual(k, timing.take_key({"text": "hi"}, {"exaggeration": 0.6}, "chatterbox"))
        self.assertEqual(k, timing.take_key({"text": "hi", "start": 3}, {"exaggeration": 0.5}, "chatterbox"))


if __name__ == "__main__":
    unittest.main()
