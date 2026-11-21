import contextlib
import io
import re
import unittest

from agents.routines import release
from agents.routines.__main__ import main
from agents.routines.tools.release import CHANNELS
from utils.cache.files import PROJECT_ROOT, read_text

SKILLS = PROJECT_ROOT / "agents" / "skills"
CHANNEL_FILE = re.compile(
    r"(?<![\w-])([a-z][a-z-]*)\.(?:<language>|[a-z]{2})\.(?:txt|md|html|svg)\b"
)


def _channel_owners() -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for skill in sorted(SKILLS.glob("i8-release-*/SKILL.md")):
        for stem in CHANNEL_FILE.findall(read_text(str(skill))):
            owners.setdefault(stem, set()).add(skill.parent.name)
    return owners


class TestRoutine(unittest.TestCase):
    def test_show_prints_every_step(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["show", "release"]), 0)
        for index, step in enumerate(release.STEPS, start=1):
            self.assertIn(f"{index}. {step.label}", out.getvalue())

    def test_every_channel_step_reads_the_brief_only(self) -> None:
        ids = [step.id for step in release.STEPS]
        channel_steps = [
            step
            for step in release.STEPS
            if step.label.startswith("From brief.yml only")
        ]
        self.assertEqual(len(channel_steps), 6)
        for step in channel_steps:
            with self.subTest(step=step.id):
                self.assertLess(ids.index("brief"), ids.index(step.id))
                self.assertNotIn("CHANGELOG", step.label)

    def test_a_stub_run_reaches_the_hand_over(self) -> None:
        reached, step = [], release.STEPS[0]
        steps = {s.id: s for s in release.STEPS}
        while step.kind != "terminal":
            reached.append(step.id)
            step = steps[step.nxt or step.branches[0][1]]
        self.assertEqual(step.id, "handover")
        self.assertIn("check", reached)


class TestChannelSkills(unittest.TestCase):
    def test_every_channel_is_written_by_exactly_one_skill(self) -> None:
        owners = _channel_owners()
        self.assertEqual(sorted(owners), sorted(CHANNELS))
        shared = {stem: names for stem, names in owners.items() if len(names) > 1}
        self.assertEqual(shared, {})

    def test_each_skill_states_the_bounds_the_check_enforces(self) -> None:
        owners = _channel_owners()
        for stem, channel in CHANNELS.items():
            (skill,) = owners[stem]
            text = read_text(str(SKILLS / skill / "SKILL.md"))
            for bound in channel.bounds:
                for value in (bound.low, bound.high):
                    if value >= 10:
                        with self.subTest(stem=stem, value=value):
                            self.assertIn(f"{value:,}", text)


if __name__ == "__main__":
    unittest.main()
