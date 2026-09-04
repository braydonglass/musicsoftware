"""What a Key hands out, and what it holds on to."""

import unittest

from harmony.core.key import Key


class TestKeyParsing(unittest.TestCase):
    def test_reads_the_ordinary_spellings(self):
        self.assertEqual(str(Key.parse("C major")), "C major")
        self.assertEqual(str(Key.parse("f# minor")), "F# minor")
        self.assertEqual(str(Key.parse("Eb major")), "Eb major")

    def test_a_double_flat_key_is_readable(self):
        self.assertEqual(Key.parse("Bbb major").tonic_alteration, -2)

    def test_no_key_carries_a_triple_accidental(self):
        for text in ("C### major", "Bbbb minor", "F#########  major".strip()):
            with self.assertRaises(ValueError):
                Key.parse(text)


class TestSignature(unittest.TestCase):
    def test_spells_the_key(self):
        # G major: one sharp, on F.
        signature = Key.parse("G major").signature()
        sharped = {letter for letter, alt in signature.items() if alt == 1}
        self.assertEqual(sharped, {3})       # F is letter index 3

    def test_minor_uses_the_natural_seventh(self):
        # A minor has no accidental; the raised G# is an accidental, not
        # part of the signature.
        self.assertEqual(set(Key.parse("A minor").signature().values()), {0})

    def test_hands_out_a_fresh_dict_each_call(self):
        key = Key.parse("C major")
        first = key.signature()
        first[0] = 99
        self.assertEqual(key.signature()[0], 0)

    def test_an_edited_copy_cannot_reach_an_equal_key(self):
        one, two = Key.parse("D major"), Key.parse("D major")
        one.signature().clear()
        self.assertEqual(len(two.signature()), 7)
        self.assertFalse(two.is_altered(two.scale_degree(7)))

    def test_the_cache_is_bounded(self):
        # Keyed on the Key itself, and a cached Key is never freed - so an
        # unbounded cache would retain every key the process ever parsed.
        self.assertEqual(Key._signature.cache_info().maxsize, 128)


if __name__ == "__main__":
    unittest.main()
