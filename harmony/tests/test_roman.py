"""Milestone 2 and 3 gates: keys, scale degrees, and numeral parsing."""

import unittest

from harmony.core.key import Key
from harmony.core.pitch import Pitch, PitchClass
from harmony.core.roman import RomanNumeralError, parse

PC = PitchClass.parse


def names(spec):
    return [str(pc) for pc in spec.pitch_classes]


class TestKey(unittest.TestCase):
    def test_parsing(self):
        self.assertEqual(str(Key.parse("C major")), "C major")
        self.assertEqual(str(Key.parse("f# minor")), "F# minor")
        self.assertEqual(str(Key.parse("Eb major")), "Eb major")

    def test_sharp_keys_spell_sharps(self):
        self.assertEqual(str(Key.parse("G major").scale_degree(7)), "F#")

    def test_flat_keys_spell_flats(self):
        self.assertEqual(str(Key.parse("Eb major").scale_degree(4)), "Ab")

    def test_minor_seventh_degree_has_two_forms(self):
        a_minor = Key.parse("a minor")
        self.assertEqual(str(a_minor.scale_degree(7)), "G")
        self.assertEqual(str(a_minor.scale_degree(7, raised=True)), "G#")

    def test_leading_tone_of_sharp_minor_is_double_lettered(self):
        # f# minor's leading tone is E#, not F natural.
        self.assertEqual(str(Key.parse("f# minor").leading_tone), "E#")

    def test_altered_detection(self):
        a_minor = Key.parse("a minor")
        self.assertTrue(a_minor.is_altered(PC("G#")))
        self.assertFalse(a_minor.is_altered(PC("G")))
        self.assertTrue(a_minor.is_leading_tone(PC("G#")))
        self.assertFalse(a_minor.is_leading_tone(PC("G")))


class TestRomanNumerals(unittest.TestCase):
    def setUp(self):
        self.C = Key.parse("C major")
        self.c = Key.parse("c minor")
        self.a = Key.parse("a minor")

    def test_dominant_triad_major(self):
        self.assertEqual(names(parse("V", self.C)), ["G", "B", "D"])

    def test_minor_mode_raises_seventh_for_dominant(self):
        self.assertEqual(names(parse("V", self.c)), ["G", "B", "D"])
        self.assertEqual(names(parse("V", self.a)), ["E", "G#", "B"])

    def test_minor_mode_keeps_natural_seventh_for_subtonic(self):
        self.assertEqual(names(parse("VII", self.c)), ["Bb", "D", "F"])
        self.assertEqual(names(parse("III", self.c)), ["Eb", "G", "Bb"])
        self.assertEqual(names(parse("VI", self.c)), ["Ab", "C", "Eb"])

    def test_leading_tone_chord_raises(self):
        self.assertEqual(names(parse("vii°", self.c)), ["B", "D", "F"])
        self.assertEqual(names(parse("vii°7", self.c)), ["B", "D", "F", "Ab"])

    def test_half_diminished_in_major(self):
        self.assertEqual(names(parse("viiø7", self.C)), ["B", "D", "F", "A"])

    def test_inversions_set_the_bass(self):
        self.assertEqual(str(parse("V65", self.C).bass_pc), "B")
        self.assertEqual(str(parse("V43", self.C).bass_pc), "D")
        self.assertEqual(str(parse("V42", self.C).bass_pc), "F")
        self.assertEqual(str(parse("V2", self.C).bass_pc), "F")
        self.assertEqual(str(parse("vii°6", self.C).bass_pc), "D")
        self.assertEqual(str(parse("I6", self.C).bass_pc), "E")

    def test_seventh_is_tagged(self):
        self.assertEqual(str(parse("V7", self.C).seventh_pc), "F")
        self.assertEqual(str(parse("ii7", self.C).seventh_pc), "C")
        self.assertEqual(str(parse("IV7", self.C).seventh_pc), "E")
        self.assertIsNone(parse("V", self.C).seventh_pc)

    def test_leading_tone_is_tagged(self):
        self.assertEqual(str(parse("V", self.C).leading_tone_pc), "B")
        self.assertEqual(str(parse("V", self.a).leading_tone_pc), "G#")
        self.assertIsNone(parse("IV", self.C).leading_tone_pc)

    def test_diatonic_triad_qualities(self):
        self.assertEqual(names(parse("ii", self.C)), ["D", "F", "A"])
        self.assertEqual(names(parse("iii", self.C)), ["E", "G", "B"])
        self.assertEqual(names(parse("IV", self.C)), ["F", "A", "C"])
        self.assertEqual(names(parse("vi", self.C)), ["A", "C", "E"])
        self.assertEqual(names(parse("ii°", self.c)), ["D", "F", "Ab"])

    def test_readable_errors(self):
        for bad in ("Xq7", "VIII", "V9", "VII°", "viiø"):
            with self.assertRaises((RomanNumeralError, ValueError), msg=bad):
                parse(bad, self.C)

    def test_chromatic_chords_are_refused_with_the_diatonic_alternative(self):
        # Bare "vii" asserts a minor triad, which in C major is B D F#.
        with self.assertRaises(RomanNumeralError) as caught:
            parse("vii", self.C)
        self.assertIn("F#", str(caught.exception))
        self.assertIn("vii°", str(caught.exception))
        # "ii" in minor asserts a minor triad against a diatonic Ab.
        with self.assertRaises(RomanNumeralError):
            parse("ii", self.c)
        # but the sanctioned raised seventh still passes
        self.assertEqual(names(parse("V", self.c)), ["G", "B", "D"])
        self.assertEqual(names(parse("v", self.c)), ["G", "Bb", "D"])

    def test_cadential_six_four_is_refused_with_a_reason(self):
        with self.assertRaises(RomanNumeralError) as caught:
            parse("I64", self.C)
        self.assertIn("cadential", str(caught.exception).lower())

    def test_passing_six_four_still_parses(self):
        self.assertEqual(str(parse("V64", self.C).bass_pc), "D")


if __name__ == "__main__":
    unittest.main()
