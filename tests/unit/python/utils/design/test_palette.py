import unittest
from typing import ClassVar

from ansible.errors import AnsibleError

from plugins.lookup.design_palette import LookupModule
from utils.design.palette import (
    CONTRAST_BODY_TEXT,
    CONTRAST_TEXT,
    CONTRAST_UI,
    SCALE_STEPS,
    STATUS_HUES,
    build_palette,
    contrast,
    parse_hex,
    relative_luminance,
)


class TestPaletteContrast(unittest.TestCase):
    BASES: ClassVar[tuple[str, ...]] = (
        "#001f3f",
        "#FFA500",
        "#FFFF00",
        "#00FF00",
        "#808080",
        "#FF00FF",
    )
    MODES: ClassVar[tuple[str, ...]] = ("light", "dark")
    LINK_APART_FROM_TEXT: ClassVar[float] = 1.4

    def _assert_min(
        self, fg: str, backgrounds: list[str], target: float, label: str
    ) -> None:
        worst = min(contrast(fg, bg) for bg in backgrounds)
        self.assertGreaterEqual(
            worst, target, f"{label}: {fg} reaches only {worst:.2f}"
        )

    def test_semantic_tokens_meet_wcag_targets(self) -> None:
        for base in self.BASES:
            palette = build_palette(base)
            for mode in self.MODES:
                with self.subTest(base=base, mode=mode):
                    t = palette[mode]
                    surfaces = [t[f"--design-surface-{i}"] for i in (1, 2, 3)]
                    content = surfaces[:2]
                    self._assert_min(
                        t["--design-text"], surfaces, CONTRAST_BODY_TEXT, "text"
                    )
                    self._assert_min(
                        t["--design-text-muted"], surfaces, CONTRAST_TEXT, "muted"
                    )
                    self._assert_min(
                        t["--design-link"], surfaces, CONTRAST_TEXT, "link"
                    )
                    self._assert_min(
                        t["--design-primary"], content, CONTRAST_UI, "primary"
                    )
                    self._assert_min(
                        t["--design-border-strong"], content, CONTRAST_UI, "border"
                    )
                    self._assert_min(
                        t["--design-on-primary"],
                        [t["--design-primary"]],
                        CONTRAST_TEXT,
                        "on-primary",
                    )
                    for status in STATUS_HUES:
                        color = t[f"--design-{status}"]
                        self._assert_min(
                            color,
                            [*surfaces, t[f"--design-{status}-subtle"]],
                            CONTRAST_TEXT,
                            status,
                        )
                        self._assert_min(
                            t[f"--design-on-{status}"],
                            [color],
                            CONTRAST_TEXT,
                            f"on-{status}",
                        )

    def test_interaction_states_keep_their_text_readable(self) -> None:
        for base in self.BASES:
            palette = build_palette(base)
            for mode in self.MODES:
                with self.subTest(base=base, mode=mode):
                    t = palette[mode]
                    states = [
                        t["--design-surface-hover"],
                        t["--design-surface-active"],
                    ]
                    self._assert_min(
                        t["--design-text"], states, CONTRAST_BODY_TEXT, "text"
                    )
                    self._assert_min(
                        t["--design-text-muted"], states, CONTRAST_TEXT, "muted"
                    )
                    for name in ("link", *STATUS_HUES):
                        self._assert_min(
                            t[f"--design-{name}"], states, CONTRAST_TEXT, name
                        )
                    for fill in ("primary", *STATUS_HUES):
                        self._assert_min(
                            t[f"--design-on-{fill}"],
                            [t[f"--design-{fill}-hover"], t[f"--design-{fill}-active"]],
                            CONTRAST_TEXT,
                            f"on-{fill}",
                        )

    def test_frame_is_a_deep_brand_surface_in_both_modes(self) -> None:
        for base in self.BASES:
            palette = build_palette(base)
            for mode in self.MODES:
                with self.subTest(base=base, mode=mode):
                    t = palette[mode]
                    frame = t["--design-frame"]
                    self._assert_min(
                        t["--design-on-frame"],
                        [
                            frame,
                            t["--design-frame-hover"],
                            t["--design-frame-active"],
                        ],
                        CONTRAST_BODY_TEXT,
                        "on-frame",
                    )
                    self.assertLess(
                        relative_luminance(frame),
                        relative_luminance(palette["light"]["--design-surface-3"]),
                        "the frame must stay darker than every light surface",
                    )
                    self.assertGreaterEqual(
                        contrast(frame, t["--design-surface-1"]),
                        1.2,
                        "the frame must stand out against the page",
                    )

    def test_light_frame_keeps_a_deep_base_unchanged(self) -> None:
        self.assertEqual(build_palette("#001f3f")["light"]["--design-frame"], "#001f3f")

    def test_light_primary_keeps_a_compliant_base_unchanged(self) -> None:
        self.assertEqual(
            build_palette("#001f3f")["light"]["--design-primary"], "#001f3f"
        )

    def test_a_link_stays_apart_from_body_text(self) -> None:
        for base in (*self.BASES, "#000000", "#ffffff"):
            palette = build_palette(base)
            for mode in self.MODES:
                with self.subTest(base=base, mode=mode):
                    t = palette[mode]
                    self.assertGreaterEqual(
                        contrast(t["--design-link"], t["--design-text"]),
                        self.LINK_APART_FROM_TEXT,
                        "a link as dark or as light as body text cannot be told from it",
                    )

    def test_dark_mode_does_not_invert_the_light_palette(self) -> None:
        palette = build_palette("#001f3f")
        self.assertNotEqual(
            palette["light"]["--design-primary"], palette["dark"]["--design-primary"]
        )
        self.assertLess(
            relative_luminance(palette["dark"]["--design-surface-1"]),
            relative_luminance(palette["light"]["--design-surface-1"]),
        )


class TestPaletteScale(unittest.TestCase):
    def test_scales_run_from_surface_to_text_in_both_modes(self) -> None:
        palette = build_palette("#001f3f")
        for mode, descending in (("light", True), ("dark", False)):
            for prefix in ("primary", "neutral"):
                with self.subTest(mode=mode, prefix=prefix):
                    values = [
                        palette[mode][f"--design-{prefix}-{step}"]
                        for step in SCALE_STEPS
                    ]
                    luminances = [relative_luminance(v) for v in values]
                    self.assertEqual(luminances, sorted(luminances, reverse=descending))

    def test_every_color_carries_a_matching_rgb_triplet(self) -> None:
        palette = build_palette("#FFA500")
        for section in palette.values():
            for name, value in section.items():
                if name.endswith("-rgb"):
                    continue
                expected = ", ".join(str(round(c * 255)) for c in parse_hex(value))
                self.assertEqual(section[f"{name}-rgb"], expected, name)


class TestPaletteInput(unittest.TestCase):
    def test_short_hex_equals_long_hex(self) -> None:
        self.assertEqual(build_palette("#fa0"), build_palette("#ffaa00"))

    def test_invalid_hex_names_the_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "'navy'"):
            build_palette("navy")

    def test_lookup_turns_invalid_hex_into_ansible_error(self) -> None:
        with self.assertRaisesRegex(AnsibleError, "#12345"):
            LookupModule().run(["#12345"])

    def test_lookup_returns_the_palette(self) -> None:
        self.assertEqual(LookupModule().run(["#001f3f"]), [build_palette("#001f3f")])


if __name__ == "__main__":
    unittest.main()
