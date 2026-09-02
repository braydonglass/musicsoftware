"""The HTTP layer's payloads.

No rule logic lives in the web layer, so what is worth testing is that it
carries the engine's answers out intact - the places a passing tone may go,
the refusals with the rule that caused them, and a melody that is only
partly pinned.
"""

import unittest
from unittest import mock

from harmony.core.checker import check, errors_only
from harmony.core.key import Key
from harmony.core.melody import parse_soprano, transpose
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

    def test_a_hole_does_not_break_pruning_at_the_other_notes(self):
        """The bug: any hole collapsed workable()'s pruning for every note.

        With the hole filled in, note 2 prunes to ['i']. With it left as a
        hole, that pruning must survive - only the hole's own (unopinionated,
        note-free) slot is exempt from having a real answer.
        """
        with_note = candidates_payload(
            {"key": "c minor", "soprano": "C4 C4 C4 Ab4", "profile": "strict"})
        with_hole = candidates_payload(
            {"key": "c minor", "soprano": "_ C4 C4 Ab4", "profile": "strict"})
        numerals = lambda notes, i: [o["numeral"] for o in notes[i]["options"]]
        self.assertEqual(numerals(with_hole["notes"], 1), numerals(with_note["notes"], 1))
        self.assertEqual(numerals(with_hole["notes"], 2), numerals(with_note["notes"], 2))

    def test_a_hole_does_not_break_the_phrase_level_suggestion(self):
        """The bug: any hole collapsed suggest() to the naive first-choice
        answer it exists to avoid - here, an empty string at the hole and
        the degenerate i-i-ii-i pattern everywhere else.
        """
        suggested = candidates_payload(
            {"key": "c minor", "soprano": "C4 _ Eb4 D4 C4", "profile": "strict"})["suggested"]
        self.assertNotIn("", suggested)
        self.assertNotEqual(suggested, ["i", "i", "i", "ii°6", "i"])
        self.assertIn(suggested[-1], ("i", "i6"))

    def test_workable_and_suggest_share_generate_between_them(self):
        """The redundancy: workable() and suggest() used to redo the same
        (note index, chord) -> voicings search independently.

        candidates_payload now hands both one cache, so a (index, token)
        pair generate() has already answered for workable() is not asked
        again for suggest() - it's reused, not recomputed.
        """
        import harmony.core.melody as melody_mod
        real_generate = melody_mod.generate
        calls = []

        def counting(spec, key, profile, soprano=None):
            calls.append((spec.numeral, soprano))
            return real_generate(spec, key, profile, soprano=soprano)

        with mock.patch.object(melody_mod, "generate", counting):
            # No repeated note: a (chord, note) pair repeating for a
            # legitimate reason (the same note recurring) would otherwise
            # be indistinguishable here from the redundancy under test.
            payload = candidates_payload(
                {"key": "C major", "soprano": "C4 D4 E4 F4 G4", "profile": "strict"})
        self.assertTrue(payload["ok"])
        self.assertEqual(len(calls), len(set(calls)),
                         f"generate() was asked the same (chord, note) question twice: {calls}")


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
        suggested = payload["suggested"]
        self.assertNotEqual(naive, suggested)

        # What the difference is now. Taking the first chord that fits used
        # to give something the solver could not connect at all; it no
        # longer does, because the options are pruned to chords that lie on
        # a complete path and the first of those is a safe one. What it
        # still gives is a line that goes nowhere - i i ii°6 i i ii°6 i ii°6,
        # two chords alternating, ending on neither a tonic nor a dominant.
        self.assertLessEqual(
            len(set(naive)), 3,
            f"the naive choice used to be this static: {naive}")
        self.assertNotIn(naive[-1], ("i", "i6", "V", "V6", "V7"),
                         f"the naive choice used to end nowhere: {naive}")
        self.assertGreater(
            len(set(suggested)), len(set(naive)),
            f"reading the phrase should move more: {suggested}")
        self.assertIn(suggested[-1], ("i", "i6", "V", "V6", "V7"),
                      f"and should end somewhere: {suggested}")

    def test_it_ends_somewhere(self):
        """A phrase reaching a tonic should cadence on one."""
        suggested = self.suggestion("C major", "C4 C4 G4 G4 A4 A4 G4")
        self.assertIn(suggested[-1], ("I", "I6"))

    def test_a_note_with_no_chord_does_not_crash_it(self):
        payload = candidates_payload({"key": "c minor", "soprano": "E5 F5 G5"})
        self.assertEqual(len(payload["suggested"]), 3)
        self.assertEqual(payload["suggested"][0], "")


class TheSuggestionCanActuallyBePlayed(unittest.TestCase):
    """A chord per note is not a progression, twice over.

    Each chord offered lies on some complete path. Picking the best one
    note at a time can still step off all of them, and filtering afterwards
    does not save it: the beam fills with high-scoring lines that cannot be
    played and prunes away the ones that can. Twinkle in D minor came back
    i iv V i iv vii°7 i, where iv to V has no legal pair of voicings at all.
    """

    TUNES = ["E5 E5 F5 G5 G5 F5 E5 D5", "C4 C4 G4 G4 A4 A4 G4",
             "E4 D4 C4 D4 E4 E4 E4", "G4 A4 G4 F4 E4 F4 G4",
             "C4 D4 E4 C4 C4 D4 E4 C4", "C5 C5 C5 G4 A4 A4 G4",
             "G4 E4 G4 G4 E4 G4", "C4 C4 C4 D4 E4 D4 C4 E4",
             "G4 E4 E4 F4 D4 D4 C4 D4 E4 F4 G4", "G4 C5 C5 C5 B4 C5 D5 C5"]
    KEYS = ["C major", "G major", "F major", "Eb major", "A major",
            "a minor", "d minor", "c minor", "e minor", "bb minor", "f# minor"]

    def test_every_tune_in_every_key_gets_a_playable_suggestion(self):
        profile = Profile.load("strict")
        low, high = profile.ranges["soprano"]
        home = Key.parse("C major")
        for tune in self.TUNES:
            for key_text in self.KEYS:
                with self.subTest(tune=tune, key=key_text):
                    key = Key.parse(key_text)
                    melody = transpose(parse_soprano(tune), home, key, low, high)
                    text = " ".join(str(p) for p in melody)
                    suggested = candidates_payload({"key": key_text, "soprano": text})["suggested"]
                    self.assertEqual(len(suggested), len(melody))
                    # the point: it realizes, not merely that it exists
                    solve(parse_progression(" ".join(suggested), key), key,
                          profile, soprano=melody)

    def test_a_long_tune_gets_the_wider_search_it_needs(self):
        """Eleven notes of Lightly Row in C minor need the second pass.

        The narrow beam produces nothing playable for it. Widening only when
        the narrow one fails is what keeps the seven-note tunes cheap, so
        the widening has to actually happen when it is needed.
        """
        key = Key.parse("c minor")
        profile = Profile.load("strict")
        low, high = profile.ranges["soprano"]
        melody = transpose(
            parse_soprano("G4 E4 E4 F4 D4 D4 C4 D4 E4 F4 G4"),
            Key.parse("C major"), key, low, high)
        text = " ".join(str(p) for p in melody)
        suggested = candidates_payload({"key": "c minor", "soprano": text})["suggested"]
        solve(parse_progression(" ".join(suggested), key), key, profile,
              soprano=melody)


class TransposingMovesTheTuneAsLittleAsItCan(unittest.TestCase):
    """It used to take the first octave that fitted, which is not the same.

    C major to G and back returned E4 where E5 went out, because E4 is in
    the soprano's range and the search stopped at the first thing that was.
    That also parks the tune at the bottom of the range, where the three
    voices underneath have the least room.
    """

    def test_it_picks_the_nearest_octave_that_fits(self):
        profile = Profile.load("strict")
        low, high = profile.ranges["soprano"]
        g, c = Key.parse("G major"), Key.parse("C major")
        # B4-ish in G is mi; mi in C is E, and E5 is nearer to it than E4
        moved = transpose(parse_soprano("B4 B4 C5 D5 D5 C5 B4 A4"),
                                g, c, low, high)
        self.assertEqual(" ".join(str(p) for p in moved),
                         "E5 E5 F5 G5 G5 F5 E5 D5")

    def test_it_never_leaves_the_range(self):
        profile = Profile.load("strict")
        low, high = profile.ranges["soprano"]
        home = Key.parse("C major")
        for key_text in ["C major", "F# major", "Gb major", "d# minor",
                         "bb minor", "B major", "Db major"]:
            with self.subTest(key=key_text):
                moved = transpose(parse_soprano("E5 E5 F5 G5 G5 F5 E5 D5"),
                                        home, Key.parse(key_text), low, high)
                for p in moved:
                    self.assertLessEqual(low.midi, p.midi, f"{p} below {low}")
                    self.assertLessEqual(p.midi, high.midi, f"{p} above {high}")
