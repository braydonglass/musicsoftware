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
        self.assertEqual(sorted(offer), ["chord", "note", "refusedBy", "voice"])

    def test_an_undecorated_result_is_one_whole_beat_per_chord(self):
        result = self.payload()["results"][0]
        self.assertEqual([e["beats"] for e in result["events"]], [1, 1, 1, 1, 1])

    def test_a_chosen_passing_tone_splits_its_beat(self):
        offers = self.payload()["results"][0]["opportunities"]
        free = [o for o in offers if not o["refusedBy"]][0]
        result = self.payload(passing=[[free["chord"], free["voice"]]])["results"][0]
        self.assertEqual(len(result["events"]), 6)
        self.assertEqual([e["beats"] for e in result["events"][:2]], [0.5, 0.5])
        self.assertEqual(result["events"][1]["passing"], [free["voice"]])

    def test_a_passing_event_carries_drawable_notes_for_all_four_voices(self):
        offers = self.payload()["results"][0]["opportunities"]
        free = [o for o in offers if not o["refusedBy"]][0]
        result = self.payload(passing=[[free["chord"], free["voice"]]])["results"][0]
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

    def test_the_exported_file_carries_the_chosen_passing_tones(self):
        plain, _ = midi_for(dict(self.BASE))
        decorated, _ = midi_for(dict(self.BASE, passing="0:bass"))
        self.assertNotEqual(plain, decorated)
        self.assertGreater(len(decorated), len(plain))

    def test_the_file_is_named_after_the_key_and_progression(self):
        _, stem = midi_for(dict(self.BASE))
        self.assertEqual(stem, "c-major-i-vi-iv-v-i")

    def test_an_unavailable_choice_is_ignored_rather_than_fatal(self):
        """A stale click must not break the download."""
        plain, _ = midi_for(dict(self.BASE))
        stale, _ = midi_for(dict(self.BASE, passing="0:soprano"))
        self.assertEqual(plain, stale)
