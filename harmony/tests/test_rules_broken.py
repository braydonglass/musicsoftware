"""Milestone 5 gate: the deliberately-broken corpus.

Each case asserts the exact violation list, not merely that something was
wrong. Every voicing here was found by searching the generator for pairs
whose only error is the one being demonstrated, so a stray extra violation
means a rule has started firing where it should not.

The two no-violation cases at the end matter most. They are what prove the
engine is reading interval quality rather than counting semitones.
"""

import unittest

from harmony.core.checker import check, errors_only, exceptions_only
from harmony.core.key import Key
from harmony.core.pitch import Pitch
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import PROFILE_DIR, Profile
from harmony.core.voice import Voicing

P = Pitch.parse


def voicing(s, a, t, b):
    return Voicing(P(s), P(a), P(t), P(b))


class BrokenCorpus(unittest.TestCase):
    def setUp(self):
        self.profile = Profile.load("kostka_payne")

    def errors(self, key, progression, voicings):
        k = Key.parse(key)
        specs = parse_progression(progression, k)
        return errors_only(check(voicings, specs, k, self.profile))

    def assert_single(self, errs, rule_id, voices):
        self.assertEqual(len(errs), 1, f"expected one error, got {[str(e) for e in errs]}")
        self.assertEqual(errs[0].rule_id, rule_id)
        self.assertEqual(set(errs[0].voices), set(voices))
        self.assertEqual(errs[0].chord_index, 0)

    def test_parallel_fifths_between_soprano_and_bass(self):
        errs = self.errors("C major", "I ii", [
            voicing("G4", "C4", "E3", "C3"),
            voicing("A4", "A3", "F3", "D3"),
        ])
        self.assert_single(errs, "parallel_perfect", ["soprano", "bass"])
        self.assertIn("fifths", errs[0].message)

    def test_parallel_octaves_between_soprano_and_tenor(self):
        errs = self.errors("C major", "I ii", [
            voicing("E4", "C4", "E3", "C3"),
            voicing("F4", "A3", "F3", "D3"),
        ])
        self.assert_single(errs, "parallel_perfect", ["soprano", "tenor"])
        self.assertIn("octaves", errs[0].message)

    def test_unequal_fourths_between_soprano_and_tenor(self):
        """A perfect fourth to an augmented fourth, moving together.

        The fourth's exact analogue of unequal_fifths, and the reason it
        needs its own rule: parallel_perfect wants both intervals perfect
        and hidden_perfect wants the arrival perfect, so an augmented
        fourth slips past both while the ear hears two fourths in parallel.
        """
        errs = self.errors("d minor", "i ii°6", [
            voicing("D5", "F4", "A3", "D3"),
            voicing("E5", "E4", "Bb3", "G2"),
        ])
        self.assert_single(errs, "unequal_fourths", ["soprano", "tenor"])
        self.assertIn("fourth", errs[0].message)

    def test_unresolved_leading_tone_in_the_soprano(self):
        errs = self.errors("C major", "V I", [
            voicing("B4", "D4", "D3", "G2"),
            voicing("E4", "C4", "E3", "C3"),
        ])
        self.assert_single(errs, "leading_tone_resolution", ["soprano"])

    def test_chordal_seventh_that_does_not_fall(self):
        errs = self.errors("C major", "V7 vi", [
            voicing("F4", "B3", "F3", "G2"),
            voicing("E4", "C4", "C3", "A2"),
        ])
        self.assert_single(errs, "seventh_resolution", ["tenor"])

    def test_augmented_second_in_minor(self):
        # C4 up to G#4 across VI -> V: three semitones spanning two letter
        # names. Minor's raised seventh is where these appear.
        errs = self.errors("a minor", "VI V", [
            voicing("C4", "A3", "C3", "F2"),
            voicing("G#4", "G#3", "E3", "E2"),
        ])
        self.assert_single(errs, "melodic_augmented", ["soprano"])

    def test_doubled_leading_tone_is_caught_in_a_single_chord(self):
        # B in both soprano and tenor: the leading tone owes a resolution and
        # cannot pay it twice without producing parallel octaves.
        key = Key.parse("C major")
        specs = parse_progression("V", key)
        graded = check([voicing("B4", "G4", "B3", "G2")], specs, key, self.profile)
        flagged = [v for v in graded if v.rule_id == "doubled_leading_tone"]
        self.assertTrue(flagged, "doubling the leading tone must be reported")
        # Costly rather than impossible. A rule of motion outranks a rule of
        # doubling - parallels are audible, a doubled tone is not - so the
        # solver may pay this price to avoid a worse fault, and says why.
        self.assertEqual(flagged[0].severity, "warning")
        self.assertIn("motion", flagged[0].reason)

    def test_voice_crossing_is_caught(self):
        errs = self.errors("C major", "I", [voicing("C4", "E4", "G3", "C3")])
        self.assertTrue(any(e.rule_id == "voice_crossing" for e in errs))

    def test_out_of_range_is_caught(self):
        errs = self.errors("C major", "I", [voicing("G5", "E4", "C4", "C2")])
        self.assertTrue(any(e.rule_id == "voice_range" for e in errs))

    def test_no_profile_may_drop_the_leading_tone(self):
        """The bug that motivated the rule.

        A profile once priced chord completeness at zero, which let the
        solver omit the third of V - and the third of a dominant is the
        leading tone. A preference a profile may zero must never be the
        thing holding an essential tone in place.
        """
        from harmony.core.solver import realize
        key = Key.parse("d minor")
        specs = parse_progression("i V i", key)
        for name in sorted(path.stem for path in PROFILE_DIR.glob("*.json")):
            with self.subTest(profile=name):
                result = realize(specs, key, Profile.load(name))[0]
                chromas = {p.pitch_class.chroma for p in result.voicings[1].pitches}
                self.assertIn(key.leading_tone.chroma, chromas,
                              f"{name} dropped the leading tone from V")

    def test_missing_third_is_an_error_not_a_preference(self):
        # V in C major without its B, however the profile prices completeness
        errs = self.errors("C major", "V", [voicing("D5", "G4", "D4", "G2")])
        self.assertTrue(any(e.rule_id == "missing_essential_tone" for e in errs),
                        [str(e) for e in errs])

    def test_omitting_only_the_fifth_stays_a_preference(self):
        # I in C major with no G: complete enough to be legal, still not ideal
        errs = self.errors("C major", "I", [voicing("C5", "E4", "C4", "C3")])
        self.assertEqual([e.rule_id for e in errs], [], [str(e) for e in errs])

    # ---- the cases that must stay silent ----

    def test_diminished_fifth_to_perfect_fifth_is_excused_not_ignored(self):
        """The case that proves spelled storage is doing real work.

        Both voices move, both intervals span five letter names, both are six
        or seven semitones. Only quality separates them, and a checker
        comparing semitones alone would call it parallel fifths.

        It is not an error - but it is not silence either. A diminished chord
        drives every voice to a step resolution, which is what forces the
        fifths open, so the engine reports it with that reason attached.
        """
        key = Key.parse("C major")
        specs = parse_progression("vii°6 I", key)
        voicings = [voicing("F4", "B3", "F3", "D3"), voicing("G4", "C4", "E3", "C3")]
        graded = check(voicings, specs, key, self.profile)

        self.assertEqual(errors_only(graded), [], [str(e) for e in errors_only(graded)])
        waived = [v for v in exceptions_only(graded) if v.rule_id == "unequal_fifths"]
        self.assertTrue(waived, "the d5 to P5 should be reported as an exception")
        self.assertIn("tendency tone", waived[0].reason)
        # and never mistaken for genuine parallel fifths
        self.assertFalse(any(v.rule_id == "parallel_perfect" for v in graded))

    def test_a_held_fifth_is_static_not_parallel(self):
        # soprano and alto hold a perfect fifth while only the bass moves
        errs = self.errors("C major", "I I6", [
            voicing("G4", "C4", "E3", "C3"),
            voicing("G4", "C4", "E3", "E2"),
        ])
        self.assertEqual(errs, [], [str(e) for e in errs])

    def test_unequal_fifths_outside_those_scenarios_stay_errors(self):
        """The waiver is scoped to the chords that earn it.

        A diminished chord or a secondary dominant forces its voices to step
        resolutions. A plain dominant seventh does not, so the same interval
        motion out of V7 is still a fault.
        """
        key = Key.parse("d minor")
        specs = parse_progression("vii°7/V V", key)
        voicings = [voicing("F4", "B3", "D3", "G#2"), voicing("E4", "A3", "C#3", "A2")]
        graded = check(voicings, specs, key, self.profile)
        waived = [v for v in exceptions_only(graded) if v.rule_id == "unequal_fifths"]
        self.assertTrue(waived, "a secondary dominant should excuse this")
        self.assertIn("applied leading tone", waived[0].reason)
        self.assertEqual(errors_only(graded), [], [str(e) for e in errors_only(graded)])

    def test_frustrated_leading_tone_depends_on_which_voice(self):
        """Outer voices must resolve; an inner voice may be frustrated.

        The packet is explicit: a leading tone leaping away from the tonic is
        a fault in the soprano or bass, where it is most audible, and allowed
        in an inner voice.
        """
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        # alto B3 drops a third to G3, scale degree 5, completing the tonic
        voicings = [voicing("G4", "B3", "D3", "G2"), voicing("E4", "G3", "E3", "C3")]

        graded = check(voicings, specs, key, Profile.load("kostka_payne"))

        self.assertEqual(
            [e.rule_id for e in errors_only(graded)], [],
            f"kostka_payne excuses the frustrated leading tone: "
            f"{[str(e) for e in errors_only(graded)]}")
        waived = [v for v in exceptions_only(graded)
                  if v.rule_id == "leading_tone_resolution"]
        self.assertTrue(waived, "and reports it rather than staying silent")
        self.assertTrue(waived[0].reason, "a waived rule must say why")
        # the same leap in the soprano is a fault, whatever the profile
        outer = [voicing("B4", "G4", "D4", "G2"), voicing("G4", "E4", "C4", "C3")]
        self.assertTrue(
            any(e.rule_id == "leading_tone_resolution"
                for e in errors_only(check(outer, specs, key, self.profile))),
            "a frustrated leading tone in the soprano is still a fault")


if __name__ == "__main__":
    unittest.main()
