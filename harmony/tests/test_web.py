"""The HTTP layer's payloads.

No rule logic lives in the web layer, so what is worth testing is that it
carries the engine's answers out intact - the places a passing tone may go,
the refusals with the rule that caused them, and a melody that is only
partly pinned.
"""

import unittest

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
