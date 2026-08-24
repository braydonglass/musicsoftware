"""Borrowed chords, written with a flat.

A flat before the numeral lowers the root a semitone and keeps its letter:
the sixth degree of C is A, so its flattened form is A-flat and never
G-sharp. That spelling is the whole reason pitch is stored spelled, and it
is what makes the chord read as the borrowed sixth it is.
"""

import unittest

from harmony.core.key import Key
from harmony.core.roman import RomanNumeralError, parse, parse_progression
from harmony.core.rules.registry import Profile
from harmony.core.solver import solve


class TestFlatNumerals(unittest.TestCase):
    def spell(self, token, key_text="C major"):
        spec = parse(token, Key.parse(key_text))
        return " ".join(str(pc) for pc in spec.pitch_classes)

    def test_the_flat_sixth_is_borrowed_from_the_minor(self):
        self.assertEqual(self.spell("♭VI"), "Ab C Eb")

    def test_a_plain_b_reads_as_the_flat_sign(self):
        """The keyboard has no flat key; the page offers one, and both work."""
        self.assertEqual(self.spell("bVI"), "Ab C Eb")

    def test_the_flat_third_and_seventh(self):
        self.assertEqual(self.spell("♭III"), "Eb G Bb")
        self.assertEqual(self.spell("♭VII"), "Bb D F")

    def test_the_letter_is_kept_and_only_the_alteration_moves(self):
        """A-flat, never G-sharp: the sixth degree owns the letter A."""
        spec = parse("♭VI", Key.parse("C major"))
        self.assertEqual(str(spec.root_pc), "Ab")

    def test_case_still_carries_the_quality(self):
        self.assertEqual(self.spell("♭vi"), "Ab Cb Eb")

    def test_a_figure_still_applies(self):
        spec = parse("♭VI6", Key.parse("C major"))
        self.assertEqual(str(spec.bass_pc), "C")

    def test_flattening_an_already_lowered_degree_is_refused(self):
        """In a minor key the sixth is lowered already; ♭VI would be A double
        flat, which is nobody's intention."""
        with self.assertRaises(RomanNumeralError) as caught:
            parse("♭VI", Key.parse("c minor"))
        self.assertIn("already", str(caught.exception))

    def test_the_neapolitan_keeps_its_own_reading(self):
        """bII was answered by the Neapolitan long before this existed."""
        self.assertEqual(self.spell("bII"), "Db F Ab")


class TestMixtureRealizes(unittest.TestCase):
    def test_a_borrowed_sixth_realizes(self):
        key = Key.parse("C major")
        profile = Profile.load("strict")
        specs = parse_progression("I ♭VI V I", key)
        result = solve(specs, key, profile)[0]
        self.assertEqual(len(result.voicings), 4)
        chromas = {p.pitch_class.chroma for p in result.voicings[1].pitches}
        self.assertEqual(chromas, {8, 0, 3})          # Ab C Eb


if __name__ == "__main__":
    unittest.main()
