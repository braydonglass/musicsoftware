"""The HTTP layer's payloads.

No rule logic lives in the web layer, so what is worth testing is that it
carries the engine's answers out intact - the places a passing tone may go,
the refusals with the rule that caused them, and a melody that is only
partly pinned.
"""

import unittest

from harmony.core.key import Key
from harmony.core.melody import parse_soprano
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import Profile
from harmony.core.solver import NoRealization, solve
from harmony.web.server import candidates_payload, midi_for, realize_payload


class TestOpportunitiesInThePayload(unittest.TestCase):
    def payload(self, **kwargs):
        request = {"key_text": "C major", "progression": "I vi IV V I",
                   "profile_name": "strict", "alternates": 1}
        request.update(kwargs)
        return realize_payload(**request)

    def test_every_result_carries_the_places_a_passing_tone_may_go(self):
        result = self.payload()["results"][0]
        self.assertIn("opportunities", result)
        offer = result["opportunities"][0]
        self.assertEqual(sorted(offer),
                         ["chord", "kind", "note", "refusedBy", "slot", "voice"])

    def test_an_undecorated_result_is_one_whole_beat_per_chord(self):
        result = self.payload()["results"][0]
        self.assertEqual([e["beats"] for e in result["events"]], [1, 1, 1, 1, 1])

    def test_a_chosen_passing_tone_splits_its_beat(self):
        offers = self.payload()["results"][0]["opportunities"]
        free = [o for o in offers if not o["refusedBy"]][0]
        result = self.payload(figures=[free["slot"]])["results"][0]
        self.assertEqual(len(result["events"]), 6)
        self.assertEqual([e["beats"] for e in result["events"][:2]], [0.5, 0.5])
        self.assertEqual(result["events"][1]["decorating"], [free["voice"]])

    def test_a_passing_event_carries_drawable_notes_for_all_four_voices(self):
        offers = self.payload()["results"][0]["opportunities"]
        free = [o for o in offers if not o["refusedBy"]][0]
        result = self.payload(figures=[free["slot"]])["results"][0]
        voices = result["events"][1]["voices"]
        self.assertEqual(sorted(voices), ["alto", "bass", "soprano", "tenor"])
        self.assertIn("midi", voices["soprano"])


class TestPartlyPinnedMelody(unittest.TestCase):
    def test_a_melody_shorter_than_the_progression_is_accepted(self):
        payload = realize_payload("C major", "I IV V I", "strict", 1,
                                  soprano_text="E5 F5")
        self.assertTrue(payload["ok"])
        sopranos = [c["soprano"]["name"] for c in payload["results"][0]["chords"]]
        self.assertEqual(sopranos[:2], ["E5", "F5"])

    def test_candidates_reports_a_hole_instead_of_crashing(self):
        payload = candidates_payload(
            {"key": "C major", "soprano": "E5 _ D5", "profile": "strict"})
        self.assertTrue(payload["ok"])
        self.assertEqual([n["note"] for n in payload["notes"]], ["E5", "_", "D5"])
        self.assertEqual(payload["notes"][1]["options"], [])


class TestMidiExport(unittest.TestCase):
    BASE = {"key": "C major", "progression": "I vi IV V I", "profile": "strict"}

    def free_slot(self):
        """A figure the engine actually offers for this progression."""
        payload = realize_payload("C major", "I vi IV V I", "strict", 1)
        for offer in payload["results"][0]["opportunities"]:
            if not offer["refusedBy"]:
                return offer["slot"]
        self.fail("the engine offers nothing to decorate here")

    def test_the_exported_file_carries_the_chosen_passing_tones(self):
        plain, _ = midi_for(dict(self.BASE))
        free = self.free_slot()
        decorated, _ = midi_for(dict(self.BASE, figures=free))
        self.assertNotEqual(plain, decorated)
        self.assertGreater(len(decorated), len(plain))

    def test_the_file_is_named_after_the_key_and_progression(self):
        _, stem = midi_for(dict(self.BASE))
        self.assertEqual(stem, "c-major-i-vi-iv-v-i")

    def test_an_unavailable_choice_is_ignored_rather_than_fatal(self):
        """A stale click must not break the download."""
        plain, _ = midi_for(dict(self.BASE))
        stale, _ = midi_for(dict(self.BASE, figures="0:soprano:passing:Z9"))
        self.assertEqual(plain, stale)


class WhatIsWrittenIsOffered(unittest.TestCase):
    """The teaching vocabulary must not eat a chord the writer typed.

    candidates_for draws on a short list of chords a first harmonization
    exercise uses. That is right for an empty progression and wrong for one
    that already exists: I V+ vi IV in C major offered no V+ under any note,
    so holding the soprano rebuilt the chords from what was on offer and the
    augmented triad silently became I. Under its D-sharp there was nothing
    on offer at all.
    """

    def options_for(self, note, progression=""):
        payload = candidates_payload({
            "key": "C major", "soprano": note, "progression": progression})
        return [o["numeral"] for o in payload["notes"][0]["options"]]

    def test_a_chord_outside_the_vocabulary_is_offered_once_it_is_written(self):
        self.assertNotIn("V+", self.options_for("B4"))
        self.assertIn("V+", self.options_for("B4", "I V+ vi IV"))

    def test_a_note_only_that_chord_can_carry_is_not_left_with_nothing(self):
        self.assertEqual(self.options_for("D#5"), [])
        self.assertEqual(self.options_for("D#5", "I V+ vi IV"), ["V+"])

    def test_a_numeral_the_key_cannot_spell_is_ignored_not_fatal(self):
        """Half-typed and nonsense numerals reach here constantly."""
        for junk in ("I Xq7 V", "I V+", "", "   ", "I vii"):
            with self.subTest(progression=junk):
                self.assertIn("I", self.options_for("G4", junk))

    def test_the_vocabulary_is_not_duplicated_by_what_is_written(self):
        offered = self.options_for("G4", "I I6 V V")
        self.assertEqual(len(offered), len(set(offered)))


class ChoosingChordsAcrossThePhrase(unittest.TestCase):
    """A chord per note is not the same problem as a progression.

    Taking each note's first workable chord gives every note a chord that
    carries it and a line that goes nowhere - i i ii°6 i i ii°6 i ii°6 for
    Ode to Joy in C minor - and often one the solver cannot connect at all,
    because whether two chords go together is not a fact about either of
    them by itself. suggest() reads the phrase instead.
    """

    MELODIES = [
        ("c minor", "Eb5 Eb5 F5 G5 G5 F5 Eb5 D5"),
        ("C major", "E5 E5 F5 G5 G5 F5 E5 D5"),
        ("C major", "C4 C4 G4 G4 A4 A4 G4"),
        ("C major", "E4 D4 C4 D4 E4 E4 E4"),
        ("C major", "G4 A4 G4 F4 E4 F4 G4"),
        ("a minor", "A4 B4 C5 B4 A4 G#4 A4"),
        ("g minor", "Bb4 Bb4 C5 D5 D5 C5 Bb4 A4"),
        ("G major", "D5 E5 D5 C5 B4 C5 D5"),
        ("d minor", "D5 E5 F5 E5 D5 C#5 D5"),
        ("Eb major", "G4 G4 Ab4 Bb4 Bb4 Ab4 G4 F4"),
    ]

    def suggestion(self, key_text, melody):
        payload = candidates_payload({"key": key_text, "soprano": melody})
        return payload["suggested"]

    def test_every_suggestion_actually_realizes(self):
        profile = Profile.load("strict")
        for key_text, melody in self.MELODIES:
            with self.subTest(key=key_text, melody=melody):
                key = Key.parse(key_text)
                suggested = self.suggestion(key_text, melody)
                self.assertEqual(len(suggested), len(melody.split()))
                specs = parse_progression(" ".join(suggested), key)
                solve(specs, key, profile, soprano=parse_soprano(melody))

    def test_it_beats_taking_the_first_chord_that_fits(self):
        """The failure that motivated this, kept as the example."""
        payload = candidates_payload(
            {"key": "c minor", "soprano": "Eb5 Eb5 F5 G5 G5 F5 Eb5 D5"})
        naive = [n["options"][0]["numeral"] for n in payload["notes"]]
        self.assertNotEqual(naive, payload["suggested"])
        key = Key.parse("c minor")
        melody = parse_soprano("Eb5 Eb5 F5 G5 G5 F5 Eb5 D5")
        with self.assertRaises(NoRealization):
            solve(parse_progression(" ".join(naive), key), key,
                  Profile.load("strict"), soprano=melody)

    def test_it_ends_somewhere(self):
        """A phrase reaching a tonic should cadence on one."""
        suggested = self.suggestion("C major", "C4 C4 G4 G4 A4 A4 G4")
        self.assertIn(suggested[-1], ("I", "I6"))

    def test_a_note_with_no_chord_does_not_crash_it(self):
        payload = candidates_payload({"key": "c minor", "soprano": "E5 F5 G5"})
        self.assertEqual(len(payload["suggested"]), 3)
        self.assertEqual(payload["suggested"][0], "")
