"""Breaking a realization into a keyboard figure.

Two things are worth pinning here. The rule that finds the note above the
soprano has to spell chromatics the way the chord spells them, or an
augmented sixth resolves to the wrong letter. And the ladder the figure
steps through has to drop pitches two voices share, or a doubled root makes
the figure strike the same key twice in a row.
"""

import unittest

from harmony.core.key import Key
from harmony.core.midi import TICKS_PER_BEAT, encode
from harmony.core.pitch import Pitch
from harmony.core.prelude import (ALBERTI, BACH_C, BY_ID, FORMS, OOMPAH, PULSE,
                                  WALTZ, Form, above, check, figurate,
                                  ladder_for, spans)
from harmony.core.roman import parse_progression
from harmony.core.voice import Voicing

C_MAJOR = Key.parse("C major")


def _v(soprano, alto, tenor, bass):
    return Voicing(*(Pitch.parse(t) for t in (soprano, alto, tenor, bass)))


def _spec(numeral, key=C_MAJOR):
    return parse_progression(numeral, key)[0]


# The voicing Bach opens with, in this package's order.
BWV_846 = _v("C4", "G3", "E3", "C3")


class TestTheNoteAbove(unittest.TestCase):
    def above(self, numeral, note):
        return str(above(Pitch.parse(note), _spec(numeral)))

    def test_it_finds_bachs_fifth_note(self):
        self.assertEqual(self.above("I", "C4"), "E4")

    def test_bars_two_and_three(self):
        self.assertEqual(self.above("ii7", "D4"), "F4")
        self.assertEqual(self.above("V7", "D4"), "F4")

    def test_an_augmented_sixth_keeps_its_own_letter(self):
        # Ab, not G#. They are one key and two notes, and every rule about
        # resolution reads the letter.
        self.assertEqual(self.above("Ger+6", "F#4"), "Ab4")
        self.assertEqual(self.above("Ger+6", "Ab5"), "C6")

    def test_other_chromatic_chords(self):
        self.assertEqual(self.above("N6", "Db5"), "F5")
        self.assertEqual(self.above("vii°7", "Ab4"), "B4")

    def test_a_note_that_only_sounds_higher_does_not_count(self):
        # B#3 and C4 are the same key. The answer is the next letter that is
        # genuinely above, not the one that ties.
        self.assertEqual(self.above("I", "B#3"), "E4")

    def test_it_only_ever_answers_with_a_note_of_the_chord(self):
        for numeral in ("I", "ii7", "V7", "vii°7", "Ger+6", "N6", "III+"):
            spec = _spec(numeral)
            owned = {(pc.letter, pc.alteration) for pc in spec.pitch_classes}
            for start in ("C3", "F#4", "Ab4", "B#3", "Db5", "G5"):
                answer = above(Pitch.parse(start), spec)
                self.assertIn((answer.letter, answer.alteration), owned)
                self.assertGreater(answer.midi, Pitch.parse(start).midi)


class TestTheLadder(unittest.TestCase):
    def test_it_is_the_voicing_low_to_high_then_extended(self):
        rungs = ladder_for(BWV_846, _spec("I"), 5)
        self.assertEqual([str(p) for p in rungs], ["C3", "E3", "G3", "C4", "E4"])

    def test_a_doubled_pitch_is_one_rung(self):
        doubled = _v("C5", "C5", "E4", "C3")        # soprano and alto in unison
        rungs = ladder_for(doubled, _spec("I"), 5)
        self.assertEqual(len(rungs), 5)
        self.assertEqual(len(set(p.midi for p in rungs)), 5)
        # the unison collapsed, so the ladder had to reach further up
        self.assertEqual([str(p) for p in rungs], ["C3", "E4", "C5", "E5", "G5"])

    def test_the_ladder_always_rises(self):
        for form in FORMS:
            rungs = ladder_for(BWV_846, _spec("V7"), form.rungs)
            self.assertEqual([p.midi for p in rungs], sorted(p.midi for p in rungs))


class TestBachC(unittest.TestCase):
    def setUp(self):
        self.notes = figurate([BWV_846], [_spec("I")], BACH_C)

    def test_it_is_bar_one(self):
        figure = ["C3", "E3", "G3", "C4", "E4", "G3", "C4", "E4"]
        self.assertEqual([str(n.pitch) for n in self.notes], figure + figure)

    def test_the_two_low_notes_are_held_under_the_figure(self):
        held = [(str(n.pitch), n.start, n.beats)
                for n in self.notes if n.beats > BACH_C.unit]
        self.assertEqual(held, [("C3", 0.0, 2.0), ("E3", 0.25, 1.75),
                                ("C3", 2.0, 2.0), ("E3", 2.25, 1.75)])

    def test_the_figure_never_strikes_the_same_key_twice_running(self):
        struck = [n for n in self.notes if n.beats <= BACH_C.unit]
        for one, two in zip(struck, struck[1:]):
            self.assertNotEqual(one.pitch.midi, two.pitch.midi)


class TestEveryForm(unittest.TestCase):
    def test_the_pattern_tiles_the_bar_exactly(self):
        # One note to every step of the grid, no gap and no overrun. A form
        # whose pattern did not divide its bar would show up here as a short
        # last group rather than as a wrong-sounding file.
        for form in FORMS:
            notes = figurate([BWV_846], [_spec("I")], form)
            # a step may strike several rungs at once, so it is the set of
            # start times that has to tile the bar, not the note count
            struck = sorted(set(round(n.start, 6)
                                for n in notes if n.rung not in form.drone))
            steps = int(round(form.beats_per_measure / form.unit))
            self.assertEqual(struck, [round(i * form.unit, 6)
                                      for i in range(steps)])
            self.assertAlmostEqual(max(n.start + n.beats for n in notes),
                                   form.beats_per_measure, places=6)

    def test_one_chord_fills_one_bar(self):
        specs = parse_progression("I ii7 V7 I", C_MAJOR)
        voicings = [BWV_846] * 4
        for form in FORMS:
            notes = figurate(voicings, specs, form)
            for index in range(4):
                bar = [n for n in notes if n.chord == index]
                self.assertTrue(bar)
                low = index * form.beats_per_measure
                self.assertAlmostEqual(min(n.start for n in bar), low, places=6)
                self.assertLessEqual(max(n.start + n.beats for n in bar),
                                     low + form.beats_per_measure + 1e-9)

    def test_no_form_strikes_a_note_it_is_already_holding(self):
        # Two notes of one MIDI number overlapping is a shorter sound, not a
        # thicker one: the encoder's note-off for the second ends the first.
        specs = parse_progression("I ii7 V7 vii°7 Ger+6 N6", C_MAJOR)
        for form in FORMS:
            notes = figurate([BWV_846] * len(specs), specs, form)
            for a in notes:
                for b in notes:
                    if a is b or a.pitch.midi != b.pitch.midi:
                        continue
                    self.assertFalse(a.start < b.start < a.start + a.beats,
                                     f"{form.id} restrikes {a.pitch} while holding it")

    def test_the_alberti_melody_is_held_across_its_bar(self):
        notes = figurate([BWV_846], [_spec("I")], ALBERTI)
        drone = [n for n in notes if n.rung == 3]
        self.assertEqual(len(drone), 1)
        self.assertEqual((drone[0].start, drone[0].beats), (0.0, 4.0))

    def test_the_waltz_is_in_three(self):
        self.assertEqual(WALTZ.meter, (3, 4))
        self.assertEqual(WALTZ.beats_per_measure, 3.0)

    def test_every_form_has_its_own_name_and_a_ladder_it_fits_in(self):
        self.assertEqual(len(BY_ID), len(FORMS))
        for form in FORMS:
            self.assertTrue(form.label)
            reached = max(max(form.step(i) for i in range(len(form.pattern))))
            self.assertLess(reached, form.rungs)
            self.assertTrue(all(d < form.rungs for d in form.drone))


class TestChordSteps(unittest.TestCase):
    """A step that strikes several rungs at once.

    An accompaniment is not an arpeggio with the notes rearranged. A waltz's
    second and third beats are a chord, and no ordering of single rungs makes
    one - which is why a step is a set of rungs rather than one.
    """

    def test_the_waltz_answers_its_bass_with_a_chord(self):
        notes = figurate([BWV_846], [_spec("I")], OOMPAH)
        by_start = {}
        for note in notes:
            by_start.setdefault(note.start, []).append(str(note.pitch))
        self.assertEqual(by_start[0.0], ["C3"])
        self.assertEqual(sorted(by_start[1.0]), ["C4", "E3", "G3"])
        self.assertEqual(sorted(by_start[2.0]), ["C4", "E3", "G3"])

    def test_the_notes_of_one_step_sound_together_and_equally_long(self):
        for form in (OOMPAH, PULSE):
            # the drone is not part of any step, and outlasts all of them
            notes = [n for n in figurate([BWV_846], [_spec("I")], form)
                     if n.rung not in form.drone]
            by_start = {}
            for note in notes:
                by_start.setdefault(note.start, []).append(note)
            for group in by_start.values():
                self.assertEqual(len(set(n.beats for n in group)), 1)
                self.assertEqual(len(set(n.rung for n in group)), len(group))

    def test_a_step_reaching_past_its_ladder_is_refused(self):
        with self.assertRaises(ValueError):
            check(Form(id="bad", label="", meter=(4, 4), unit=1.0,
                       pattern=(0, (1, 9)), rungs=4))


class TestBadForms(unittest.TestCase):
    def test_a_pattern_that_strikes_its_own_drone_is_refused(self):
        with self.assertRaises(ValueError):
            check(Form(id="bad", label="", meter=(4, 4), unit=0.5,
                       pattern=(0, 1, 2), drone=(1,), rungs=3))

    def test_a_pattern_that_strikes_its_own_sustain_is_refused(self):
        with self.assertRaises(ValueError):
            check(Form(id="bad", label="", meter=(4, 4), unit=0.5,
                       pattern=(0, 1, 0), sustained=(0,), rungs=2))

    def test_a_pattern_that_does_not_divide_its_bar_is_refused(self):
        with self.assertRaises(ValueError):
            Form(id="bad", label="", meter=(4, 4), unit=0.5,
                 pattern=(0, 1, 2), rungs=3).repeats


class TestEncoding(unittest.TestCase):
    def test_the_spans_reach_the_encoder(self):
        notes = figurate([BWV_846], [_spec("I")], BACH_C)
        data = encode(spans(notes), meter=BACH_C.meter)
        self.assertTrue(data.startswith(b"MThd"))

    def test_a_held_note_lasts_as_long_as_it_is_held(self):
        notes = figurate([BWV_846], [_spec("I")], BACH_C)
        low = [s for s in spans(notes) if s[2] == Pitch.parse("C3").midi]
        self.assertEqual(low, [(0.0, 2.0, 48), (2.0, 4.0, 48)])

    def test_a_waltz_writes_three_four(self):
        notes = figurate([BWV_846], [_spec("I")], WALTZ)
        data = encode(spans(notes), meter=WALTZ.meter)
        at = data.index(b"\xFF\x58\x04")
        self.assertEqual(data[at + 3], 3)         # numerator
        self.assertEqual(data[at + 4], 2)         # log2 of the denominator

    def test_the_ticks_land_on_the_grid(self):
        notes = figurate([BWV_846], [_spec("I")], BACH_C)
        for start, end, _ in spans(notes):
            self.assertEqual((start * TICKS_PER_BEAT) % (TICKS_PER_BEAT // 4), 0)
            self.assertGreater(end, start)


class TestRefusals(unittest.TestCase):
    def test_a_length_mismatch_is_refused(self):
        with self.assertRaises(ValueError):
            figurate([BWV_846], parse_progression("I V", C_MAJOR), BACH_C)


if __name__ == "__main__":
    unittest.main()
