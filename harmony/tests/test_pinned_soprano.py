"""A melody may be pinned only in part.

The engine chooses a soprano when none is given. Adding a chord to a
progression then rewrites the whole tune, which throws away a melody the
writer wanted to keep. A partly pinned melody is the fix: the notes that
were chosen stay put, and only the new chord is free.
"""

import contextlib
import io
import unittest

from harmony.cli import main
from harmony.core.key import Key
from harmony.core.melody import parse_soprano
from harmony.core.pitch import Pitch
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import Profile
from harmony.core.solver import realize, solve


class TestParseSopranoHoles(unittest.TestCase):
    def test_underscore_reads_as_a_free_note(self):
        self.assertEqual(
            parse_soprano("E5 _ D5"),
            [Pitch.parse("E5"), None, Pitch.parse("D5")],
        )


class TestPartlyPinnedRealization(unittest.TestCase):
    def setUp(self):
        self.key = Key.parse("C major")
        self.profile = Profile.load("strict")

    def realize(self, progression, melody_text):
        specs = parse_progression(progression, self.key)
        melody = parse_soprano(melody_text)
        return solve(specs, self.key, self.profile, soprano=melody)[0], specs

    def test_a_short_melody_leaves_the_later_chords_free(self):
        """Adding a chord must not throw away the notes already chosen."""
        result, _ = self.realize("I IV V I", "E5 F5")
        self.assertEqual(str(result.voicings[0].soprano), "E5")
        self.assertEqual(str(result.voicings[1].soprano), "F5")
        self.assertEqual(len(result.voicings), 4)

    def test_a_hole_inside_the_melody_is_the_engine_s_to_choose(self):
        result, _ = self.realize("I IV V I", "E5 F5 _ C5")
        pinned = [str(result.voicings[i].soprano) for i in (0, 1, 3)]
        self.assertEqual(pinned, ["E5", "F5", "C5"])

    def test_a_hole_still_realizes_all_four_voices(self):
        """A hole frees the soprano, it does not silence the chord.

        Four voices sound and the chord keeps the tones it owes. Not four
        *distinct* pitches: two voices sharing one is a priced warning in
        this engine, not a fault, so demanding four would be testing a
        preference the profile is free to set.
        """
        result, specs = self.realize("I IV V I", "E5 F5 _ C5")
        third = result.voicings[2]
        self.assertEqual(len(third.pitches), 4)
        sounding = {p.pitch_class.chroma for p in third.pitches}
        essential = {specs[2].pitch_classes[0].chroma,
                     specs[2].pitch_classes[1].chroma}
        self.assertTrue(essential <= sounding,
                        "the chord lost its root or its third")

    def test_more_notes_than_chords_is_still_refused(self):
        specs = parse_progression("I IV", self.key)
        melody = parse_soprano("E5 F5 D5 C5")
        with self.assertRaises(ValueError) as caught:
            realize(specs, self.key, self.profile, soprano=melody)
        self.assertIn("4 notes against 2 chords", str(caught.exception))


class TestHolesReachTheCommands(unittest.TestCase):
    def test_chords_command_reports_a_hole_rather_than_crashing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["chords", "--key", "C major", "--soprano", "E5 _ D5"])
        self.assertEqual(code, 0)
        self.assertIn("the engine chooses", out.getvalue())
