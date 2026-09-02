"""Milestone 1 gate: pitch construction and interval measurement."""

import unittest

from harmony.core.pitch import (
    Interval,
    Pitch,
    UnspellableInterval,
    interval_between,
    pitch_at_interval,
)

P = Pitch.parse


class TestPitch(unittest.TestCase):
    def test_midi_of_reference_pitches(self):
        self.assertEqual(P("C4").midi, 60)
        self.assertEqual(P("A4").midi, 69)

    def test_enharmonics_sound_alike_but_are_not_equal(self):
        self.assertEqual(P("F#4").midi, P("Gb4").midi)
        self.assertNotEqual(P("F#4").diatonic_index, P("Gb4").diatonic_index)
        self.assertNotEqual(P("F#4"), P("Gb4"))

    def test_round_trip_formatting(self):
        for text in ("C4", "F#4", "Bb3", "C##5", "Ebb2"):
            self.assertEqual(str(P(text)), text)

    def test_octave_seam_at_b_to_c(self):
        # B3 and C4 are adjacent semitones with different octave numbers,
        # which is the most common off-by-one in pitch code.
        self.assertEqual(P("B3").midi, 59)
        self.assertEqual(P("C4").midi, 60)

    def test_rejects_nonsense(self):
        for text in ("H4", "C", "4C", "C#*4"):
            with self.assertRaises(ValueError):
                P(text)


class TestIntervalMeasurement(unittest.TestCase):
    def test_inclusive_counting(self):
        # C to G touches five letters and is a fifth, though the index
        # difference is 4.
        self.assertEqual(interval_between(P("C4"), P("G4")), Interval(5, 7))

    def test_unison_is_generic_one(self):
        self.assertEqual(interval_between(P("C4"), P("C4")), Interval(1, 0))

    def test_same_sound_different_interval(self):
        self.assertEqual(interval_between(P("C4"), P("F#4")), Interval(4, 6))
        self.assertEqual(interval_between(P("C4"), P("Gb4")), Interval(5, 6))

    def test_diminished_second_is_not_a_unison(self):
        # Zero semitones, generic size 2. If this returns a unison the
        # diatonic_index tiebreak in interval_between has gone missing.
        self.assertEqual(interval_between(P("C#4"), P("Db4")), Interval(2, 0))

    def test_minor_second(self):
        self.assertEqual(interval_between(P("C4"), P("Db4")), Interval(2, 1))

    def test_octave_seam(self):
        self.assertEqual(interval_between(P("B3"), P("C4")), Interval(2, 1))

    def test_descending_keeps_generic_positive(self):
        self.assertEqual(interval_between(P("C4"), P("G3")), Interval(4, 5))

    def test_qualities(self):
        self.assertEqual(interval_between(P("C4"), P("G4")).quality, "perfect")
        self.assertEqual(interval_between(P("C4"), P("F#4")).quality, "augmented")
        self.assertEqual(interval_between(P("C4"), P("Gb4")).quality, "diminished")
        self.assertEqual(interval_between(P("C4"), P("E4")).quality, "major")
        self.assertEqual(interval_between(P("C4"), P("Eb4")).quality, "minor")

    def test_compound_reduces(self):
        twelfth = interval_between(P("C4"), P("G5"))
        self.assertEqual(twelfth, Interval(12, 19))
        self.assertEqual(twelfth.simplified(), Interval(5, 7))


class TestPitchConstruction(unittest.TestCase):
    def test_spelling_follows_generic_size(self):
        self.assertEqual(pitch_at_interval(P("C4"), Interval(4, 6), "up"), P("F#4"))
        self.assertEqual(pitch_at_interval(P("C4"), Interval(5, 6), "up"), P("Gb4"))

    def test_octave_seam_increments(self):
        self.assertEqual(pitch_at_interval(P("B3"), Interval(2, 1), "up"), P("C4"))

    def test_descending(self):
        self.assertEqual(pitch_at_interval(P("C4"), Interval(3, 4), "down"), P("Ab3"))
        self.assertEqual(pitch_at_interval(P("C4"), Interval(5, 7), "down"), P("F3"))

    def test_raises_rather_than_spelling_a_triple_sharp(self):
        with self.assertRaises(UnspellableInterval):
            pitch_at_interval(P("C#4"), Interval(2, 4), "up")

    def test_round_trip_against_measurement(self):
        base = P("C4")
        for generic, specific in [(2, 1), (2, 2), (3, 3), (3, 4), (4, 5),
                                  (4, 6), (5, 7), (6, 9), (7, 11), (8, 12)]:
            interval = Interval(generic, specific)
            for direction in ("up", "down"):
                built = pitch_at_interval(base, interval, direction)
                self.assertEqual(
                    interval_between(base, built), interval,
                    f"{interval} {direction} from {base} came back as {built}",
                )


if __name__ == "__main__":
    unittest.main()
