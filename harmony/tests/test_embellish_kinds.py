"""The figures a writer can ask for, and where each one sits.

Four sit on the weak half of the beat they decorate - passing, neighbour,
anticipation, escape - and two on the strong half, where a dissonance
sounds first and resolves after: the suspension and the appoggiatura.

None of them is given a time signature. The first half of a beat is
stronger than its second, which is a fact about the beat; which beats of a
bar are strong is a fact about the bar, and the engine still does not know
it. See the limit recorded at the end of the README.
"""

import unittest

from harmony.core.embellish import STRONG_HALF, WEAK_HALF, opportunities
from harmony.core.key import Key
from harmony.core.pitch import Pitch, melodic_interval
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import Profile
from harmony.core.voice import Voicing


def _v(*names):
    return Voicing(*(Pitch.parse(n) for n in names))


class KindFixture(unittest.TestCase):
    def setUp(self):
        self.key = Key.parse("C major")
        self.profile = Profile.load("strict")

    def offers(self, progression, voicings, kind=None, voice=None):
        specs = parse_progression(progression, self.key)
        found = opportunities(voicings, specs, self.key, self.profile)
        if kind:
            found = [o for o in found if o.kind == kind]
        if voice:
            found = [o for o in found if o.voice == voice]
        return found


class TestWeakHalfFigures(KindFixture):
    def test_a_neighbour_needs_a_repeated_note(self):
        """The voice comes back to where it started, so the decoration is
        the step it leaves and returns from."""
        found = self.offers("I IV", [_v("E5", "C4", "G3", "C3"),
                                     _v("F5", "C4", "A3", "F3")],
                            kind="neighbour", voice="alto")
        self.assertTrue(found)
        pitches = sorted(str(o.pitch) for o in found)
        self.assertEqual(pitches, ["B3", "D4"])   # lower and upper neighbour

    def test_a_neighbour_is_not_offered_where_the_voice_moves(self):
        found = self.offers("I IV", [_v("E5", "C4", "G3", "C3"),
                                     _v("F5", "D4", "A3", "F3")],
                            kind="neighbour", voice="alto")
        self.assertEqual(found, [])

    def test_an_anticipation_arrives_early_on_the_next_note(self):
        found = self.offers("V I", [_v("D5", "G4", "B3", "G3"),
                                    _v("C5", "G4", "C4", "C3")],
                            kind="anticipation", voice="soprano")
        self.assertTrue(found)
        self.assertEqual(str(found[0].pitch), "C5")

    def test_an_anticipation_needs_the_voice_to_move(self):
        found = self.offers("V I", [_v("D5", "G4", "B3", "G3"),
                                    _v("C5", "G4", "C4", "C3")],
                            kind="anticipation", voice="alto")
        self.assertEqual(found, [])

    def test_an_escape_tone_steps_away_and_then_leaps(self):
        """Away from the note in the direction the line is not going, then
        a leap to where it was going."""
        found = self.offers("I vi", [_v("C5", "G4", "E4", "C3"),
                                     _v("A4", "E4", "C4", "A2")],
                            kind="escape", voice="soprano")
        self.assertTrue(found)
        escape = found[0].pitch
        self.assertEqual(str(escape), "D5")
        self.assertEqual(melodic_interval(Pitch.parse("C5"), escape)[0].generic, 2)
        self.assertGreater(
            melodic_interval(escape, Pitch.parse("A4"))[0].generic, 2)

    def test_every_weak_half_figure_is_marked_as_such(self):
        specs = parse_progression("I IV V I", self.key)
        vs = [_v("E5", "C4", "G3", "C3"), _v("F5", "C4", "A3", "F3"),
              _v("D5", "B3", "G3", "G3"), _v("C5", "C4", "E4", "C3")]
        for o in opportunities(vs, specs, self.key, self.profile):
            with self.subTest(kind=o.kind):
                self.assertIn(o.kind, WEAK_HALF + STRONG_HALF)


if __name__ == "__main__":
    unittest.main()
