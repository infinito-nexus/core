import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import silence  # noqa: E402

PLAN = {
    "scenes": [{"id": "intro", "start": 0, "end": 4, "music": True, "lines": []},
               {"id": "s1", "start": 4, "end": 12, "lines": ["a", "b"]},
               {"id": "s2", "start": 12, "end": 20, "lines": ["c"]}],
    "lines": {"a": {"start": 4.5, "end": 6.0}, "b": {"start": 6.35, "end": 8.0}, "c": {"start": 11.0, "end": 14.0}},
}


def stem(path, talk):
    """Write a 20 s WAV: a tone where talk lists (start, end), silence elsewhere."""
    expr = "+".join(f"between(t,{a},{b})" for a, b in talk)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=20:sample_rate=16000",
                    "-af", f"volume='if({expr},1,0)':eval=frame", str(path)], check=True)


class SilenceCheck(unittest.TestCase):
    def test_clean_chapter_passes_and_intro_outro_are_exempt(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "v.wav"
            stem(p, [(4.5, 6.0), (6.35, 8.0), (8.6, 11.0), (11.0, 14.0)])
            self.assertEqual(silence.findings(silence.quiet_spans(p), PLAN), [])

    def test_gap_over_warn_warns_and_over_fail_fails(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "v.wav"
            stem(p, [(4.5, 6.0), (6.35, 8.0), (9.6, 11.0), (11.0, 11.5), (14.5, 15)])
            plan = {**PLAN, "lines": {**PLAN["lines"], "c": {"start": 11.0, "end": 15.0}}}
            found = silence.findings(silence.quiet_spans(p), plan)
            levels = [(f[0], f[3]) for f in found]
            self.assertIn(("WARN", "s1"), levels)
            self.assertIn(("FAIL", "s2"), levels)
            fail = next(f for f in found if f[0] == "FAIL")
            self.assertAlmostEqual(fail[2] - fail[1], 3.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
