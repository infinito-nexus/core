from __future__ import annotations

import unittest

from ._spec_secrets_fakes import RAW, VALUE, WINDOW, load_masker
from ._spec_secrets_forms import (
    ENCODER_TRIGGERS,
    MARK_TRIGGERS,
    NORMALIZED_TRIGGERS,
    SNAPSHOT_TRIGGERS,
    SPECIALS,
    SPLIT_TRIGGERS,
    TRIGGERS,
    basic_leaks,
    chunked,
    form_leaks,
    literal_leaks,
    spaced_leaks,
)

UNDECODED_VALUES = (
    "        for data, _starts, _ends in views(form)\n",
    "        for data in [form]\n",
)
NO_ENCODINGS = (
    "    texts += [data for value in values for data in encoded_forms(value)]\n",
    "",
)
HELD = 'held = max(len(buffer) - HOLD, buffer.rfind(b"\\n") + 1, 0)'
HOLD = 64 * WINDOW
SAMPLE = "q\"w'z\\yk&j<n>m%r+s t/u.v:x(é\U0001f600)"
UNSTRIPPED = ("if MARK.search(buffer) else", "if False else")
UNMARKED = ("for start, end in MARKS.values()", "for start, end in ()")
UNQUOTED = ("        quoted_text,\n", "")
LT_ESCAPE = ('.replace("<", ', '.replace(">", ')
REGEX_ESCAPE = ('r"[.*+?^${}()|[', 'r"[')
NO_REPR = (
    UNQUOTED,
    ("repr(text)[1:-1]", "text"),
    ("ascii(text)[1:-1]", "text"),
    ('repr(text.encode("utf-8"))[2:-1]', "text"),
)
DECODERS = {
    "ansi": ['    rb"(?P<ansi>\\x1b\\[[0-?]*[ -/]*[@-~])",\n', ["ansi_inverse_diff"]],
    "sgr": ['    rb"(?P<sgr>\\[[0-9;]*m)",\n', ["junit_sgr_remnant"]],
    "hex": [
        '    rb"%(?P<hex>[0-9A-Fa-f]{2})",\n',
        [
            "percent_encoded",
            "form_encoded",
            "double_percent",
            "form_then_percent",
            "encode_uri_component",
            "encode_uri",
            "url_search_params",
        ],
    ],
    "entity": [
        '    rb"&(?P<entity>#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});?",\n',
        ["xml", "json_in_xml_attribute", "html_decimal", "html_hex", "html_named"],
    ],
    "unit": [
        '    rb"\\\\u(?P<unit>[0-9A-Fa-f]{4})",\n',
        ["json", "json_in_xml_attribute", "json_in_json", "json_unicode_escapes"],
    ],
    "pair": [
        '    rb"\\\\u(?P<high>[dD][89abAB][0-9A-Fa-f]{2})\\\\u(?P<low>[dD][c-fC-F][0-9A-Fa-f]{2})",\n',
        ["json", "json_in_xml_attribute", "json_in_json", "json_unicode_escapes"],
    ],
    "wide": [
        '    rb"\\\\(?:U|u\\{)(?P<wide>[0-9A-Fa-f]{1,8})\\}?",\n',
        ["js_code_point_escapes", "ascii_repr"],
    ],
    "byte": [
        '    rb"\\\\x(?P<byte>[0-9A-Fa-f]{2})",\n',
        ["ascii_repr", "python_bytes_repr"],
    ],
    "char": [
        '    rb"\\\\(?P<char>[ -/:-@\\[-`{-~bft])",\n',
        [
            "json",
            "json_unicode",
            "json_in_xml_attribute",
            "single_quoted_inspect",
            "json_in_json",
            "ascii_repr",
            "python_bytes_repr",
        ],
    ],
    "css": ['    rb"\\\\(?P<css>[0-9A-Fa-f]{1,6}) ?",\n', ["css_hex"]],
    "plus": [
        '    rb"(?P<plus>\\+)",\n',
        ["form_encoded", "form_then_percent", "url_search_params"],
    ],
    "quote": ["    rb\"(?P<quote>'')\",\n", ["yaml_single_quoted"]],
}
NEW_RULE = (DECODERS["plus"][0], DECODERS["plus"][0] + '    rb"(?P<tilde>~)",\n')
NO_QUOTE = (
    (DECODERS["quote"][0], ""),
    ('    "quote": (lambda text: text.replace("\'", "\'\'"),),\n', ""),
)
UNNORMALIZED = (
    "    values = list(dict.fromkeys([*values, *map(normalized, values)]))\n",
    "",
)
SNAPSHOT_LINES = {
    "ab'cdefgh": (
        "- 'heading \"Token: ab''cdefgh\"'\n",
        "- 'heading \"Token: ***\"'\n",
    ),
    "abcd  efgh": ('- heading "Token: abcd efgh"\n', '- heading "Token: ***"\n'),
    "ab\N{ZERO WIDTH SPACE}cd\N{SOFT HYPHEN}efgh": (
        '- heading "Token: abcdefgh"\n',
        '- heading "Token: ***"\n',
    ),
}


def snapshot_leaks(module) -> list[str]:
    """Mask the ARIA snapshot line a ``toMatchAriaSnapshot`` failure prints.

    Args:
        module: the loaded masker.

    Returns:
        The values of ``SNAPSHOT_LINES`` whose line is not masked as expected.
    """
    found = []
    for value, (line, expected) in SNAPSHOT_LINES.items():
        stream = module.Stream(module.windows([value.encode()]))
        if stream.feed(line.encode(), final=True) != expected.encode():
            found.append(value)
    return found


def mapping_gaps(module) -> list[str]:
    """Hold every decoder rule against the encoders that write its escape.

    Args:
        module: the loaded masker.

    Returns:
        The rule names of ``ESCAPES`` without an entry in ``ENCODERS`` or
        ``MARKS`` and the entries without a rule, else each encoder whose
        form of ``SAMPLE`` holds no escape of its rule or that no view
        decodes back to ``SAMPLE``.
    """
    names = module.windows.__globals__
    escape, encoders, marks = names["ESCAPE"], names["ENCODERS"], names["MARKS"]
    kinds, mirrored = set(escape.groupindex) - {"high"}, set(encoders) | set(marks)
    if kinds != mirrored:
        return sorted(kinds ^ mirrored)
    forms = [
        (kind, encode(SAMPLE)) for kind, found in encoders.items() for encode in found
    ]
    forms += [
        (kind, f"{start}{SAMPLE[0]}{end}{SAMPLE[1:]}")
        for kind, (start, end) in marks.items()
    ]
    gaps = []
    for kind, form in forms:
        data = form.encode()
        found = {match.lastgroup for match in escape.finditer(data)}
        decoded = {view for view, _starts, _ends in names["views"](data)}
        if kind not in found or SAMPLE.encode() not in decoded:
            gaps.append(f"{kind}: {form!r}")
    return gaps


class TestSpecSecretsEncoding(unittest.TestCase):
    def test_every_form_a_value_reaches_the_output_in_is_masked(self) -> None:
        module = load_masker()
        self.assertEqual(form_leaks(module, VALUE), [])
        self.assertEqual(basic_leaks(module), [])
        self.assertFalse(spaced_leaks(module))

    def test_a_value_that_holds_escapes_itself_is_masked_in_every_form(self) -> None:
        self.assertEqual(literal_leaks(load_masker()), [])

    def test_a_nine_byte_value_of_every_escaped_class_is_masked_in_every_form(
        self,
    ) -> None:
        self.assertEqual(len(SPECIALS.encode()), 9)
        self.assertEqual(form_leaks(load_masker(), SPECIALS), [])

    def test_each_decoder_rule_has_an_encoder_whose_form_it_decodes(self) -> None:
        self.assertEqual(mapping_gaps(load_masker()), [])

    def test_an_aria_snapshot_masks_a_doubled_quote_and_a_normalised_name(
        self,
    ) -> None:
        self.assertEqual(snapshot_leaks(load_masker()), [])

    def test_a_value_across_feeds_is_masked_and_held_back_bytes_stay_few(self) -> None:
        module = load_masker()
        for size in (1, 5, 4096):
            with self.subTest(size=size):
                self.assertTrue(chunked(module, size))
        stream = module.Stream(module.windows([RAW]))
        for _ in range(HOLD):
            stream.feed(RAW[:13])
            self.assertLessEqual(len(stream.pending), HOLD)
        stream = module.Stream(module.windows([RAW]))
        self.assertEqual(stream.feed(b"started\n"), b"started\n")


class TestSpecSecretsEncodingNegativeControls(unittest.TestCase):
    def test_each_form_leaks_without_its_decoder(self) -> None:
        for name, (line, leaking) in DECODERS.items():
            with self.subTest(decoder=name):
                decoderless = load_masker((line, ""), NO_ENCODINGS)
                self.assertEqual(form_leaks(decoderless, VALUE), leaking)
        decoderless = load_masker((DECODERS["hex"][0], ""), NO_ENCODINGS)
        self.assertTrue(spaced_leaks(decoderless))
        for old, new, leaking in (
            (
                "DEPTH = 2",
                "DEPTH = 1",
                [
                    "json_in_xml_attribute",
                    "double_percent",
                    "form_then_percent",
                    "json_in_json",
                ],
            ),
            (
                "for form in {value} | base64_forms(value)",
                "for form in {value}",
                ["base64", "base64_urlsafe_unpadded"],
            ),
            (" | hex_forms(value)", "", ["node_buffer", "hex_unspaced"]),
            (
                'if kind == "hex" or (kind == "byte" and octets):',
                'if kind == "hex":',
                ["python_bytes_repr"],
            ),
        ):
            with self.subTest(old=old):
                changed = load_masker((old, new), NO_ENCODINGS)
                self.assertEqual(form_leaks(changed, VALUE), leaking)

    def test_a_rule_without_an_encoder_or_an_encoder_without_a_rule_is_caught(
        self,
    ) -> None:
        self.assertEqual(mapping_gaps(load_masker(NEW_RULE)), ["tilde"])
        renamed = load_masker(('"css": (', '"cssx": ('))
        self.assertEqual(mapping_gaps(renamed), ["css", "cssx"])

    def test_each_trigger_leaks_once_its_encoder_is_dropped(self) -> None:
        for replacements, leaking in (
            ((UNQUOTED,), "nine_bytes_quote_in_a_locator"),
            (NO_REPR, "nine_bytes_quotes_in_a_python_repr"),
            ((LT_ESCAPE,), "nine_bytes_lt_in_html_safe_json"),
            ((REGEX_ESCAPE,), "nine_bytes_dot_in_a_regex"),
        ):
            with self.subTest(trigger=leaking):
                self.assertIn(leaking, literal_leaks(load_masker(*replacements)))

    def test_a_doubled_quote_leaks_without_its_rule_and_encoder(self) -> None:
        unquoted = load_masker(*NO_QUOTE)
        self.assertLessEqual(set(SNAPSHOT_TRIGGERS), set(literal_leaks(unquoted)))
        self.assertEqual(snapshot_leaks(unquoted), ["ab'cdefgh"])

    def test_a_normalised_name_leaks_without_the_normalised_windows(self) -> None:
        unnormalized = load_masker(UNNORMALIZED)
        self.assertLessEqual(set(NORMALIZED_TRIGGERS), set(literal_leaks(unnormalized)))
        self.assertEqual(snapshot_leaks(unnormalized), list(SNAPSHOT_LINES)[1:])

    def test_a_highlight_leaks_without_the_stripped_view_or_the_marked_forms(
        self,
    ) -> None:
        unstripped = literal_leaks(load_masker(UNSTRIPPED))
        self.assertIn("nine_bytes_two_letters_highlighted", unstripped)
        self.assertNotIn("nine_bytes_one_letter_highlighted", unstripped)
        bare = set(literal_leaks(load_masker(UNSTRIPPED, UNMARKED)))
        self.assertLessEqual(set(MARK_TRIGGERS), bare)

    def test_windows_cut_from_the_undecoded_value_alone_are_caught(self) -> None:
        undecoded = load_masker(UNDECODED_VALUES, NO_ENCODINGS)
        self.assertLessEqual(set(TRIGGERS), set(literal_leaks(undecoded)))

    def test_windows_only_from_decoded_output_are_caught(self) -> None:
        decoded_only = load_masker(NO_ENCODINGS)
        self.assertLessEqual(
            set(SPLIT_TRIGGERS) | set(ENCODER_TRIGGERS),
            set(literal_leaks(decoded_only)),
        )

    def test_a_basic_header_behind_an_unaligned_user_is_caught(self) -> None:
        module = load_masker(("for shift in range(3):", "for shift in range(1):"))
        self.assertEqual(basic_leaks(module), ["abc", "a", "user", "admin:x"])

    def test_a_stream_without_hold_back_carry_or_line_release_is_caught(
        self,
    ) -> None:
        held = load_masker((HELD, "held = len(buffer)"))
        self.assertFalse(chunked(held, 5))
        carried = load_masker(
            ("done, carry = min(end, cut), max(end - cut, 0)", "done = min(end, cut)")
        )
        self.assertFalse(chunked(carried, 1))
        lagging = load_masker(('buffer.rfind(b"\\n") + 1, ', ""))
        stream = lagging.Stream(lagging.windows([RAW]))
        self.assertNotEqual(stream.feed(b"started\n"), b"started\n")


if __name__ == "__main__":
    unittest.main()
