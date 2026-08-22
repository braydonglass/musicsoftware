"""Passing tones the writer asks for.

The engine does not decide to decorate anything. It says where a passing
tone will fit, spells the one that fits, and refuses the ones that break
the rules already in the registry - and the refusal names the rule.
"""

import unittest

from harmony.core.embellish import apply, filling, opportunities
from harmony.core.key import Key
from harmony.core.pitch import Pitch, melodic_interval
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import Profile
from harmony.core.solver import solve
from harmony.core.voice import Voicing


class TestFilling(unittest.TestCase):
    """The note between, spelled by the key rather than by semitones."""

    def fill(self, low, high, key_text):
        got = filling(Pitch.parse(low), Pitch.parse(high), Key.parse(key_text))
        return str(got) if got is not None else None

    def test_a_rising_third_is_filled_by_the_letter_between(self):
        self.assertEqual(self.fill("E4", "G4", "C major"), "F4")

    def test_a_falling_third_is_filled_the_same_way(self):
        self.assertEqual(self.fill("G4", "E4", "C major"), "F4")

    def test_the_filling_takes_its_accidental_from_the_key(self):
        """G to B-flat in E-flat major passes through A-flat, never G-sharp."""
        self.assertEqual(self.fill("G4", "Bb4", "Eb major"), "Ab4")

    def test_a_step_has_nothing_to_fill(self):
        self.assertIsNone(self.fill("E4", "F4", "C major"))

    def test_a_leap_wider_than_a_third_is_not_a_passing_figure(self):
        self.assertIsNone(self.fill("C4", "G4", "C major"))

    def test_a_repeated_note_has_nothing_to_fill(self):
        self.assertIsNone(self.fill("E4", "E4", "C major"))


CORPUS = [
    ("C major", "I IV V I"),
    ("C major", "I vi IV V I"),
    ("C major", "I ii6 V7 I"),
    ("C major", "I V6 I IV"),
    ("a minor", "i iv V i"),
    ("Eb major", "I vi ii6 V7 I"),
]


def _v(soprano, alto, tenor, bass):
    return Voicing(*(Pitch.parse(t) for t in (soprano, alto, tenor, bass)))


class TestOpportunities(unittest.TestCase):
    def setUp(self):
        self.key = Key.parse("C major")
        self.profile = Profile.load("kostka_payne")

    def offered(self, voicings, progression):
        specs = parse_progression(progression, self.key)
        return opportunities(voicings, specs, self.key, self.profile)

    def test_nothing_is_offered_where_no_voice_moves_by_a_third(self):
        """Steps, leaps and held notes are not passing figures."""
        found = self.offered(
            [_v("E4", "C4", "G3", "C3"), _v("D4", "B3", "G3", "G2")], "I V")
        self.assertEqual(found, [])

    def test_a_passing_tone_making_parallel_fourths_is_refused_by_name(self):
        """The classic trap: the decoration makes the fault, not the chords.

        E4 over C4 is a third and G4 over D4 is a fifth, which is clean.
        Fill the soprano's third with F4 and the pair reads C4/F4 moving to
        D4/G4 - two perfect fourths running in parallel, which this profile
        polices in every pair, not only against the bass.
        """
        found = self.offered(
            [_v("E4", "C4", "G3", "C3"), _v("G4", "D4", "B3", "G2")], "I V")
        soprano = [o for o in found if o.voice == "soprano"]
        self.assertEqual(len(soprano), 1)
        self.assertEqual(str(soprano[0].pitch), "F4")
        self.assertFalse(soprano[0].available)
        self.assertEqual(soprano[0].refused_by, "parallel_perfect")

    def test_every_offer_is_a_step_from_both_of_its_neighbours(self):
        """Whatever is offered must be a real passing figure."""
        for key_text, prog in CORPUS:
            key = Key.parse(key_text)
            specs = parse_progression(prog, key)
            voicings = solve(specs, key, self.profile)[0].voicings
            for offer in opportunities(voicings, specs, key, self.profile):
                with self.subTest(key=key_text, progression=prog, offer=offer):
                    before = voicings[offer.chord][offer.voice]
                    after = voicings[offer.chord + 1][offer.voice]
                    self.assertEqual(melodic_interval(before, offer.pitch)[0].generic, 2)
                    self.assertEqual(melodic_interval(offer.pitch, after)[0].generic, 2)

    def test_the_corpus_offers_passing_tones_somewhere(self):
        """A finder that never finds anything would pass every other test."""
        total = 0
        for key_text, prog in CORPUS:
            key = Key.parse(key_text)
            specs = parse_progression(prog, key)
            voicings = solve(specs, key, self.profile)[0].voicings
            total += sum(1 for o in opportunities(voicings, specs, key, self.profile)
                         if o.available)
        self.assertGreater(total, 0)


class TestApply(unittest.TestCase):
    """Placing the passing tones a writer has chosen."""

    def setUp(self):
        self.key = Key.parse("C major")
        self.profile = Profile.load("kostka_payne")
        self.specs = parse_progression("I IV V I", self.key)
        self.voicings = solve(self.specs, self.key, self.profile)[0].voicings

    def place(self, chosen):
        return apply(self.voicings, self.specs, self.key, self.profile, chosen)

    def test_choosing_nothing_leaves_one_whole_beat_per_chord(self):
        events, refused = self.place([])
        self.assertEqual(refused, [])
        self.assertEqual([e.voicing for e in events], self.voicings)
        self.assertEqual([e.beats for e in events], [1.0] * 4)
        self.assertEqual([e.passing for e in events], [()] * 4)

    def test_a_chosen_tone_splits_its_beat_in_half(self):
        events, refused = self.place([(0, "soprano")])
        self.assertEqual(refused, [])
        self.assertEqual(len(events), 5)
        self.assertEqual([e.beats for e in events[:2]], [0.5, 0.5])
        self.assertEqual(events[0].voicing, self.voicings[0])
        self.assertEqual(events[1].passing, ("soprano",))

    def test_the_weak_half_moves_one_voice_and_holds_the_rest(self):
        events, _ = self.place([(0, "soprano")])
        held, weak = events[0].voicing, events[1].voicing
        self.assertNotEqual(weak.soprano, held.soprano)
        self.assertEqual((weak.alto, weak.tenor, weak.bass),
                         (held.alto, held.tenor, held.bass))

    def test_the_music_keeps_its_length(self):
        events, _ = self.place([(0, "soprano"), (0, "tenor")])
        self.assertEqual(sum(e.beats for e in events), float(len(self.specs)))

    def test_two_compatible_tones_share_one_weak_half(self):
        """Both passing tones sound together; the beat splits once, not twice."""
        events, refused = self.place([(0, "soprano"), (0, "tenor")])
        self.assertEqual(refused, [])
        self.assertEqual(len(events), 5)
        self.assertEqual(set(events[1].passing), {"soprano", "tenor"})


class TestApplyRefuses(unittest.TestCase):
    def setUp(self):
        self.key = Key.parse("C major")
        self.profile = Profile.load("kostka_payne")

    def test_a_tone_the_rules_forbid_is_not_placed(self):
        specs = parse_progression("I V", self.key)
        voicings = [_v("E4", "C4", "G3", "C3"), _v("G4", "D4", "B3", "G2")]
        events, refused = apply(voicings, specs, self.key, self.profile,
                                [(0, "soprano")])
        self.assertEqual([e.beats for e in events], [1.0, 1.0])
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0].refused_by, "parallel_perfect")

    def test_two_tones_legal_alone_can_be_illegal_together(self):
        """Each widens the gap by a third; together they break the octave.

        The numerals here are carriers. opportunities and apply grade
        sonority and motion, never whether a voicing spells the chord it
        is written under - that is the checker's job - so these voicings
        are built to isolate the spacing rule and nothing else.
        """
        specs = parse_progression("I V", self.key)
        voicings = [_v("B4", "D4", "E3", "G2"), _v("B4", "F4", "C3", "G2")]

        alone_alto, refused = apply(voicings, specs, self.key, self.profile,
                                    [(0, "alto")])
        self.assertEqual(refused, [], "the alto's tone is legal on its own")
        self.assertEqual(len(alone_alto), 3)

        alone_tenor, refused = apply(voicings, specs, self.key, self.profile,
                                     [(0, "tenor")])
        self.assertEqual(refused, [], "the tenor's tone is legal on its own")
        self.assertEqual(len(alone_tenor), 3)

        together, refused = apply(voicings, specs, self.key, self.profile,
                                  [(0, "alto"), (0, "tenor")])
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0].refused_by, "spacing")
        self.assertEqual(together[1].passing, ("alto",))
