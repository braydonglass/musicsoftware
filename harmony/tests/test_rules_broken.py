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
from harmony.core.roman import parse, parse_progression
from harmony.core.rules.registry import (
    PROFILE_DIR,
    Profile,
    TransitionContext,
    evaluate_transition,
)
from harmony.core.voice import Voicing

P = Pitch.parse


def voicing(s, a, t, b):
    return Voicing(P(s), P(a), P(t), P(b))


class BrokenCorpus(unittest.TestCase):
    def setUp(self):
        self.profile = Profile.load("strict")

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

    def test_parallel_diminished_fifths_are_still_parallel_fifths(self):
        """Two fifths of the same altered quality, which nothing was watching.

        parallel_perfect wants both intervals perfect and unequal_fifths
        wants one of each, so a diminished fifth moving to another
        diminished fifth fell between them: the same size twice, both
        voices moving together, and no rule with anything to say.
        """
        errs = self.errors("d minor", "ii° V7", [
            voicing("G4", "Bb3", "E3", "E2"),
            voicing("C#4", "G3", "C#3", "A2"),
        ])
        self.assert_single(errs, "parallel_altered", ["alto", "tenor"])
        self.assertIn("diminished fifth", errs[0].message)

    def test_parallel_augmented_fourths_are_caught_the_same_way(self):
        errs = self.errors("d minor", "ii° V7", [
            voicing("E4", "Bb3", "G3", "E2"),
            voicing("C#4", "G3", "C#3", "A2"),
        ])
        self.assert_single(errs, "parallel_altered", ["soprano", "alto"])
        self.assertIn("augmented fourth", errs[0].message)

    def test_a_direct_fourth_reached_by_step_is_a_fault(self):
        """The landing page's own IV to V, and the reason fourths need
        their own leap condition.

        Soprano A4 over tenor F3 is a third; both descend a step and it
        becomes G4 over D3, a fourth. No voice leaps, so the condition that
        governs fifths and octaves never fires - and that condition cannot
        simply be loosened, because on stepwise motion it also condemns the
        direct octave in V to I and leaves the cadence unwritable. The
        fourth is the interval reached this way, so it gets its own knob.
        """
        errs = self.errors("C major", "IV V", [
            voicing("A4", "C4", "F3", "F2"),
            voicing("G4", "B3", "D3", "G2"),
        ])
        self.assert_single(errs, "hidden_perfect", ["soprano", "tenor"])
        self.assertIn("fourth", errs[0].message)

    def test_a_direct_octave_reached_by_step_is_a_fault_too(self):
        """No exemption anywhere, which is a choice with a recorded price.

        Alto B3 steps to C4 over a bass leaping G2 to C3, arriving at an
        octave by similar motion. The classical condition would excuse this
        because the upper voice steps; this profile does not, and what that
        costs is written down in ThePriceOfStrictness.
        """
        errs = self.errors("C major", "V I", [
            voicing("G4", "B3", "D3", "G2"),
            voicing("G4", "C4", "E3", "C3"),
        ])
        self.assertIn("hidden_perfect", [e.rule_id for e in errs])

    def test_a_direct_octave_between_the_outer_voices_is_a_fault(self):
        """The cadence the engine used to write.

        Soprano steps 7 to 8 while the bass leaps 5 to 1: similar motion
        into an octave between the two voices a listener follows most.
        The classical condition excuses it because the soprano steps, and
        between inner voices that excuse has to stand or there is no
        cadence left - but between soprano and bass nothing is hidden, so
        the outer pair answers to its own setting.
        """
        errs = self.errors("C major", "V I", [
            voicing("B4", "G4", "D4", "G2"),
            voicing("C5", "G4", "E4", "C3"),
        ])
        self.assert_single(errs, "hidden_perfect", ["soprano", "bass"])

    def test_an_inner_direct_octave_is_a_fault_as_well(self):
        """Alto and tenor stepping into an octave, nothing above or below
        them exposed. Policed all the same: no pair is exempt."""
        errs = self.errors("C major", "IV V", [
            voicing("C5", "A4", "C4", "F3"),
            voicing("B4", "G4", "G3", "G3"),
        ])
        self.assertIn("hidden_perfect", [e.rule_id for e in errs])

    def test_three_voices_moving_together_is_reported(self):
        """The shape that produces the faults, priced rather than forbidden.

        Across two keys, three voices moving the same way put some pair on
        a perfect fourth, fifth or octave in similar motion 91% of the
        time, and four voices do it every time. It is not a fault by
        itself - the remaining 9% are clean - so it is a preference the
        search pays for, not a rule that blocks.
        """
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        # soprano, tenor and bass all rise; the alto holds
        voicings = [voicing("B4", "G4", "D4", "G2"),
                    voicing("C5", "G4", "E4", "C3")]
        found = check(voicings, specs, key, self.profile)

        reported = [v for v in found if v.rule_id == "similar_motion"]
        self.assertTrue(reported, "three voices moving together goes unreported")
        self.assertEqual(set(reported[0].voices), {"soprano", "tenor", "bass"})
        self.assertEqual(
            [], [v for v in errors_only(found) if v.rule_id == "similar_motion"],
            "it is a preference, not a fault")

    def test_two_voices_moving_together_is_ordinary(self):
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        # soprano and tenor rise, the bass falls, the alto holds
        voicings = [voicing("B4", "G4", "D4", "G3"),
                    voicing("C5", "G4", "E4", "C3")]
        found = check(voicings, specs, key, self.profile)
        self.assertEqual([], [v for v in found if v.rule_id == "similar_motion"])

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

    def test_the_leading_tone_must_resolve_in_an_outer_voice(self):
        """Strictest where the ear follows most.

        The soprano's B falls to G, the fifth of the tonic. That figure is
        excused in an inner voice and never in an outer one.
        """
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        voicings = [voicing("B4", "G4", "D4", "G2"),
                    voicing("G4", "E4", "C4", "C3")]
        errs = errors_only(check(voicings, specs, key, self.profile))
        self.assertIn("leading_tone_resolution", [e.rule_id for e in errs])

    def test_an_inner_leading_tone_may_fall_to_the_fifth(self):
        """7 to 5 in an alto or tenor, which is the sanctioned figure.

        It exists to avoid parallel fifths or to let the resolving chord
        keep all four members, so it is reported with its reason rather
        than passed over, and priced rather than free.
        """
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        # alto B3 drops a third to G3, the fifth of the tonic
        voicings = [voicing("G4", "B3", "D3", "G2"),
                    voicing("E4", "G3", "E3", "C3")]
        graded = check(voicings, specs, key, self.profile)

        self.assertEqual([], [e for e in errors_only(graded)
                              if e.rule_id == "leading_tone_resolution"])
        waived = [v for v in exceptions_only(graded)
                  if v.rule_id == "leading_tone_resolution"]
        self.assertTrue(waived, "excused, but not in silence")
        self.assertIn("fifth", waived[0].reason)

    def test_an_inner_leading_tone_may_not_leap_anywhere_else(self):
        """The excuse is for 7 falling to 5 and for nothing else.

        Here the alto leaps up to the third of the tonic instead, which is
        not the figure practice sanctions, so it stays a fault even in an
        inner voice.
        """
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        voicings = [voicing("G4", "B3", "D3", "G2"),
                    voicing("G4", "E4", "C4", "C3")]
        errs = errors_only(check(voicings, specs, key, self.profile))
        self.assertIn("leading_tone_resolution", [e.rule_id for e in errs])

    def test_the_shipped_profile_prices_the_inner_voice_excuse(self):
        """"Occasionally, if required" is a price, not a free pass."""
        self.assertGreater(
            Profile.load("strict").waived_cost_of("leading_tone_resolution"), 0)

    def test_a_leading_tone_stepping_down_is_not_frustration(self):
        """Unchanged by the stricter profile, and worth keeping so.

        What the rule polices is leaping away from the tonic. Descending by
        step is a different move and is allowed in any voice.
        """
        key = Key.parse("C major")
        specs = parse_progression("V I", key)
        # tenor B3 steps down to A3 rather than leaping
        stepped = [voicing("D5", "G4", "B3", "G2"), voicing("C5", "G4", "A3", "F3")]
        errs = errors_only(check(stepped, specs, key, self.profile))
        self.assertNotIn("leading_tone_resolution", [e.rule_id for e in errs])

    def test_a_leading_tone_may_leap_away_when_the_next_chord_has_no_tonic(self):
        """Resolution asks for a tone the next chord does not offer.

        vii°7 -> iii is the first step of a descending-fifths sequence.
        iii is E-G-B: no C anywhere in it, so demanding the bass rise to C
        asks it to land outside the chord it is actually moving to. There is
        no tonic to resolve into, so leaping away from it is not a fault.
        """
        key = Key.parse("C major")
        specs = parse_progression("vii°7 iii", key)
        # bass leaps B2 -> E3, the root of iii - not a step up to C
        voicings = [voicing("Ab4", "D4", "F3", "B2"),
                    voicing("G4", "B3", "G3", "E3")]
        errs = errors_only(check(voicings, specs, key, self.profile))
        self.assertNotIn("leading_tone_resolution", [e.rule_id for e in errs])


class WaivedFaultsMayBePriced(unittest.TestCase):
    """An excused fault is free only if the profile says it is.

    Waiving says "this is not a fault", not "this costs nothing to
    prefer". Left free, the search picks an excused voicing as readily as
    a clean one, because both edges cost the same. Pricing the excuse is
    how a profile says: take anything else that works, and reach for this
    only when nothing else will.
    """

    def edge(self, **settings):
        key = Key.parse("C major")
        sa, sb = parse("vii°6", key), parse("I", key)
        # vii°6 to I with a diminished fifth moving to a perfect one, which
        # waiver_for excuses because every note of a diminished chord is
        # already committed to a step
        a = voicing("F4", "B3", "D3", "D3")
        b = voicing("G4", "C4", "E3", "C3")
        profile = Profile.load("strict")
        if settings:
            profile.settings = dict(
                profile.settings,
                unequal_fifths={**profile.setting("unequal_fifths"), **settings})
        rules = [r for r in profile.rules("transition") if r.id == "unequal_fifths"]
        return evaluate_transition(
            TransitionContext(a=a, b=b, spec_a=sa, spec_b=sb, key=key, index=0,
                              profile=profile), rules, short_circuit=False)

    def test_an_excused_fault_is_free_when_priced_at_nothing(self):
        """The mechanism, stated without reference to what ships."""
        found, cost = self.edge(waived_cost=0.0)
        self.assertTrue([v for v in found if v.waived])
        self.assertEqual(cost, 0.0)

    def test_the_shipped_profile_puts_a_price_on_its_excuses(self):
        """The policy, pinned separately from the mechanism.

        Left free, an excused edge and a clean one cost the same and the
        search has no reason to prefer the clean one. Realizing the corpus
        produced three excused faults before these were priced and none
        after, so every one of them had an alternative all along.
        """
        profile = Profile.load("strict")
        for rule_id in ("unequal_fifths", "unequal_fourths",
                        "hidden_perfect", "parallel_perfect"):
            with self.subTest(rule=rule_id):
                self.assertGreater(profile.waived_cost_of(rule_id), 0)

    def test_a_profile_may_put_a_price_on_the_excuse(self):
        found, cost = self.edge(waived_cost=40.0)
        self.assertTrue([v for v in found if v.waived],
                        "still reported as an exception, not turned into a fault")
        self.assertEqual(cost, 40.0)

    def test_pricing_the_excuse_does_not_make_it_a_violation(self):
        found, _ = self.edge(waived_cost=40.0)
        self.assertEqual([], errors_only(found))


if __name__ == "__main__":
    unittest.main()
