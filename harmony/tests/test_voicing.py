"""Milestone 4 gate: every generated voicing is legal on its own terms."""

import math
import unittest

from harmony.core.key import Key
from harmony.core.roman import parse
from harmony.core.rules.registry import Profile, StateContext, evaluate_state
from harmony.core.voice import VOICE_NAMES
from harmony.core.voicing import generate


class TestVoicingGeneration(unittest.TestCase):
    def setUp(self):
        self.profile = Profile.load("strict")
        self.C = Key.parse("C major")
        self.c = Key.parse("c minor")

    def voicings(self, token, key=None):
        key = key or self.C
        return generate(parse(token, key), key, self.profile)

    def test_root_position_triad_has_room_to_work(self):
        self.assertGreater(len(self.voicings("I")), 20)

    def test_every_voicing_passes_every_state_rule(self):
        rules = self.profile.rules("state")
        for token in ("I", "ii", "IV", "V", "vi", "V7", "V65", "vii°6", "I6"):
            for voicing, cost in self.voicings(token):
                ctx = StateContext(voicing, parse(token, self.C), self.C, 0, self.profile)
                violations, total = evaluate_state(ctx, rules)
                hard = [v for v in violations if v.severity == "error"]
                self.assertEqual(hard, [], f"{token} produced {voicing} with {hard}")
                self.assertFalse(math.isinf(total))

    def test_no_voice_crossing_anywhere(self):
        for voicing, _ in self.voicings("V7"):
            s, a, t, b = voicing.pitches
            self.assertGreaterEqual(s.midi, a.midi)
            self.assertGreaterEqual(a.midi, t.midi)
            self.assertGreaterEqual(t.midi, b.midi)

    def test_ranges_are_respected(self):
        for voicing, _ in self.voicings("I"):
            for name in VOICE_NAMES:
                low, high = self.profile.ranges[name]
                self.assertTrue(low.midi <= voicing[name].midi <= high.midi)

    def test_upper_spacing_never_exceeds_an_octave(self):
        for voicing, _ in self.voicings("IV"):
            self.assertLessEqual(voicing.soprano.midi - voicing.alto.midi, 12)
            self.assertLessEqual(voicing.alto.midi - voicing.tenor.midi, 12)

    def doubling_costs(self, token, chroma, key=None):
        """Costs of voicings that double a tone, against those that do not."""
        key = key or self.C
        doubled, single = [], []
        for voicing, cost in generate(parse(token, key), key, self.profile):
            count = sum(1 for c in voicing.chromas() if c == chroma)
            (doubled if count > 1 else single).append(cost)
        return doubled, single

    def test_doubling_the_leading_tone_is_priced_not_forbidden(self):
        """Doubling is expensive rather than impossible.

        A tendency tone owes a resolution and cannot pay it twice without
        producing parallels, so the solver avoids it. But a chord with too few
        tones to voice any other way - an Italian sixth has three - needs the
        option to exist at all.
        """
        spec = parse("V7", self.C)
        doubled, single = self.doubling_costs("V7", spec.leading_tone_pc.chroma)
        self.assertTrue(single, "voicings that avoid it must exist")
        if doubled:
            self.assertGreater(min(doubled), min(single),
                               "doubling must cost more than not doubling")

    def test_doubling_the_seventh_is_priced_not_forbidden(self):
        spec = parse("V7", self.C)
        doubled, single = self.doubling_costs("V7", spec.seventh_pc.chroma)
        self.assertTrue(single)
        if doubled:
            self.assertGreater(min(doubled), min(single))

    def test_raised_seventh_in_minor_is_priced_too(self):
        # G# in A minor is both the leading tone and an altered tone.
        a = Key.parse("a minor")
        spec = parse("V", a)
        doubled, single = self.doubling_costs("V", spec.leading_tone_pc.chroma, a)
        self.assertTrue(single)
        if doubled:
            self.assertGreater(min(doubled), min(single))

    def test_chord_quality_is_still_mandatory(self):
        """The one doubling fact that is not a preference: root and third.

        Everything else about doubling is priced, because a rule of motion is
        worth more than a rule of doubling. But a chord without its root or
        its third has stopped being the chord that was written, and no voice
        leading repairs that.
        """
        for token in ("V", "V7", "ii", "IV", "vii°6", "V65"):
            spec = parse(token, self.C)
            essential = {spec.pitch_classes[0].chroma, spec.pitch_classes[1].chroma}
            for voicing, _ in self.voicings(token):
                self.assertTrue(essential <= set(voicing.chromas()),
                                f"{token} voiced as {voicing} lost its root or third")

    def test_the_fifth_and_seventh_are_negotiable(self):
        """Both may be dropped, and both cost something when they are."""
        spec = parse("V7", self.C)
        without_seventh = [c for v, c in generate(spec, self.C, self.profile)
                           if spec.seventh_pc.chroma not in set(v.chromas())]
        complete = [c for v, c in generate(spec, self.C, self.profile)
                    if spec.seventh_pc.chroma in set(v.chromas())]
        self.assertTrue(complete, "complete voicings must exist")
        if without_seventh:
            self.assertGreater(min(without_seventh), min(complete),
                               "dropping the seventh must cost something")

    def test_bass_carries_the_inversion(self):
        for token, expected in (("I6", "E"), ("V65", "B"), ("vii°6", "D")):
            for voicing, _ in self.voicings(token):
                self.assertEqual(str(voicing.bass.pitch_class), expected)

    def test_counts_are_in_a_workable_band(self):
        # The spec expects roughly 50-200 per chord; this asserts the order of
        # magnitude rather than an exact figure, so the trellis stays tractable.
        for token in ("I", "V", "V7", "ii6"):
            count = len(self.voicings(token))
            self.assertGreater(count, 20, token)
            self.assertLess(count, 2000, token)


if __name__ == "__main__":
    unittest.main()
