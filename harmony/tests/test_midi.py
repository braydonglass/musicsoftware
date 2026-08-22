"""Encoding a decorated realization.

The encoder used to fire all four voices together, one strike per chord.
A passing tone splits a beat, and a voice that holds through that split
must not be struck again - or every decorated chord turns into a pair of
block eighth notes, which is not what is written.
"""

import unittest

from harmony.core.embellish import Event
from harmony.core.midi import TICKS_PER_BEAT, timeline, to_bytes
from harmony.core.pitch import Pitch
from harmony.core.voice import Voicing


def _v(soprano, alto, tenor, bass):
    return Voicing(*(Pitch.parse(t) for t in (soprano, alto, tenor, bass)))


CHORD_ONE = _v("E5", "C4", "G3", "C3")
PASSING = _v("D5", "C4", "G3", "C3")       # soprano moves, the rest hold
CHORD_TWO = _v("C5", "C4", "G3", "C3")     # every voice but the soprano repeats


class TestTimeline(unittest.TestCase):
    def sounding(self, events, voice_midi):
        return [(start, end) for start, end, note in timeline(events)
                if note == voice_midi]

    def test_a_voice_holding_through_a_split_beat_is_struck_once(self):
        events = [Event(CHORD_ONE, 0.5, 0), Event(PASSING, 0.5, 0, ("soprano",))]
        self.assertEqual(self.sounding(events, Pitch.parse("C4").midi), [(0.0, 1.0)])

    def test_the_decorated_voice_is_struck_twice(self):
        events = [Event(CHORD_ONE, 0.5, 0), Event(PASSING, 0.5, 0, ("soprano",))]
        self.assertEqual(self.sounding(events, Pitch.parse("E5").midi), [(0.0, 0.5)])
        self.assertEqual(self.sounding(events, Pitch.parse("D5").midi), [(0.5, 1.0)])

    def test_a_repeated_note_across_two_chords_is_struck_again(self):
        """The harmony changed underneath it, so the note is sung again."""
        events = [Event(CHORD_ONE, 1.0, 0), Event(CHORD_TWO, 1.0, 1)]
        self.assertEqual(self.sounding(events, Pitch.parse("C4").midi),
                         [(0.0, 1.0), (1.0, 2.0)])


class TestBytes(unittest.TestCase):
    def test_an_undecorated_realization_encodes_exactly_as_before(self):
        """Whole-beat events must not change a single byte of the old output."""
        voicings = [CHORD_ONE, CHORD_TWO]
        events = [Event(CHORD_ONE, 1.0, 0), Event(CHORD_TWO, 1.0, 1)]
        self.assertEqual(to_bytes(voicings), to_bytes(events))

    def test_a_held_voice_sounds_for_the_whole_beat(self):
        events = [Event(CHORD_ONE, 0.5, 0), Event(PASSING, 0.5, 0, ("soprano",))]
        held = [(s, e) for s, e, n in timeline(events)
                if n == Pitch.parse("G3").midi][0]
        self.assertEqual((held[1] - held[0]) * TICKS_PER_BEAT, TICKS_PER_BEAT)
