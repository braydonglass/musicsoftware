"""Milestones 6 and 7: the clean corpus, the round trip, and the CLI.

The round trip is the strongest single test here. Realize a progression,
then hand the engine its own output to grade, and expect silence. It fails
loudly if the solver and the checker ever start disagreeing, which is what
would happen the moment a rule leaked into the search loop.
"""

import io
import json
import contextlib
import unittest

from harmony.cli import main
from harmony.core.checker import check, errors_only
from harmony.core.key import Key
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import PROFILE_DIR, Profile
from harmony.core.solver import NoRealization, realize, solve

def shipped_profiles():
    return sorted(path.stem for path in PROFILE_DIR.glob("*.json"))


CLEAN_CORPUS = [
    ("C major", "I IV V I"),
    ("C major", "I vi IV V I"),
    ("C major", "I ii6 V7 I"),
    ("C major", "I V6 I IV"),
    ("C major", "I IV I6 V I"),
    ("C major", "I V7 I"),
    ("C major", "I vii°6 I"),
    ("G major", "I IV V7 I"),
    ("Eb major", "I vi ii6 V7 I"),
    ("a minor", "i iv V i"),
    ("a minor", "i VI iv V i"),
    ("c minor", "i iv V7 i"),
    ("c minor", "i VI iv V i"),
    # chromatic vocabulary
    ("C major", "I V/V V I"),
    ("C major", "I vi V/V V I"),
    ("C major", "I V7/IV IV V I"),
    ("C major", "I V/vi vi IV V I"),
    ("C major", "I vii°7 I"),
    ("a minor", "i vii°7 i"),
    ("c minor", "i iv Fr+6 V"),
    ("c minor", "i iv It+6 V"),
    ("c minor", "i iv Ger+6 V"),
    ("C major", "I IV Ger+6 V"),
    ("a minor", "i VI Fr+6 V i"),
]


class TestRealize(unittest.TestCase):
    def setUp(self):
        self.profile = Profile.load("kostka_payne")

    def realize(self, key_text, progression, k=1):
        key = Key.parse(key_text)
        specs = parse_progression(progression, key)
        return solve(specs, key, self.profile, k=k), specs, key

    def test_clean_corpus_all_realize(self):
        for key_text, progression in CLEAN_CORPUS:
            with self.subTest(key=key_text, progression=progression):
                results, _, _ = self.realize(key_text, progression)
                self.assertTrue(results)
                self.assertEqual(len(results[0].voicings), len(progression.split()))

    def test_round_trip_grading_its_own_output(self):
        """realize, then check, and expect nothing back."""
        for key_text, progression in CLEAN_CORPUS:
            with self.subTest(key=key_text, progression=progression):
                results, specs, key = self.realize(key_text, progression)
                errors = errors_only(check(results[0].voicings, specs, key, self.profile))
                self.assertEqual(
                    errors, [],
                    f"{key_text} {progression}: {[str(e) for e in errors]}")

    def test_minor_dominant_carries_the_raised_seventh(self):
        results, _, _ = self.realize("a minor", "i iv V i")
        third_chord = results[0].voicings[2]
        self.assertIn("G#", [str(p.pitch_class) for p in third_chord.pitches])

    def test_alternates_are_distinct_and_all_valid(self):
        results, specs, key = self.realize("C major", "I IV V I", k=3)
        self.assertEqual(len(results), 3)
        signatures = {tuple(str(v) for v in r.voicings) for r in results}
        self.assertEqual(len(signatures), 3, "alternates are not distinct")
        for result in results:
            errors = errors_only(check(result.voicings, specs, key, self.profile))
            self.assertEqual(errors, [], [str(e) for e in errors])
        self.assertLessEqual(results[0].cost, results[-1].cost)

    def test_every_profile_realizes_and_grades_consistently(self):
        """Whatever profiles ship, not a list that can go stale."""
        for name in shipped_profiles():
            with self.subTest(profile=name):
                profile = Profile.load(name)
                key = Key.parse("C major")
                specs = parse_progression("I IV V I", key)
                result = solve(specs, key, profile)[0]
                errors = errors_only(check(result.voicings, specs, key, profile))
                self.assertEqual(errors, [], f"{name}: {[str(e) for e in errors]}")

    def test_reinversion_rescues_what_it_can(self):
        """iv -> V in minor survives only by re-voicing, and says so."""
        # V6 puts the leading tone in the bass, so the next bass must be the
        # tonic. IV cannot supply it; IV6 can.
        key = Key.parse("C major")
        specs = parse_progression("I V6 IV", key)
        with self.assertRaises(NoRealization):
            realize(specs, key, self.profile)          # exactly as written
        result = solve(specs, key, self.profile)[0]    # with re-voicing allowed
        swaps = result.substitutions(specs)
        self.assertTrue(swaps, "it should report what it changed")
        self.assertFalse(any(u.endswith("64") for _, _, u in swaps),
                         "a six-four is not a general-purpose substitute")

    def test_impossible_progression_names_the_transition_and_the_rules(self):
        """V6 puts the leading tone in the bass, so the next bass must be the tonic.

        vi cannot supply that, and the engine has to say so rather than
        shrugging. An unrealizable progression is a fact worth reporting.
        """
        key = Key.parse("C major")
        specs = parse_progression("I V6 I6 IV", key)
        with self.assertRaises(NoRealization) as caught:
            solve(specs, key, self.profile)
        message = str(caught.exception)
        self.assertIn("V6", message)
        self.assertIn("I6", message)
        # it must name a rule, not just shrug
        self.assertTrue(any(word in message for word in
                            ("leading_tone", "hidden_perfect", "parallel")),
                        f"the failure should name what blocked it: {message}")


class TestCLI(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_realize_grid(self):
        code, out, _ = self.run_cli([
            "realize", "--key", "C major", "--meter", "4/4",
            "--progression", "I IV V I"])
        self.assertEqual(code, 0)
        for voice in ("S:", "A:", "T:", "B:"):
            self.assertIn(voice, out)
        self.assertIn("no violations", out)

    def test_realize_json_is_parseable(self):
        code, out, _ = self.run_cli([
            "realize", "--key", "C major", "--progression", "I V I",
            "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["key"], "C major")
        self.assertEqual(len(data["voices"]["soprano"]), 3)

    def test_check_reports_the_planted_fault(self):
        code, out, _ = self.run_cli([
            "check", "--key", "C major", "--progression", "I ii",
            "--soprano", "G4 A4", "--alto", "G3 D4",
            "--tenor", "E3 D3", "--bass", "C3 D3"])
        self.assertEqual(code, 1)
        self.assertIn("parallel_perfect", out)
        self.assertIn("soprano", out)

    def test_check_passes_clean_input(self):
        code, out, _ = self.run_cli([
            "check", "--key", "C major", "--progression", "I I6",
            "--soprano", "C4 C4", "--alto", "G3 G3",
            "--tenor", "E3 E3", "--bass", "C3 E2"])
        self.assertEqual(code, 0)
        self.assertIn("no violations", out)

    def test_rules_listing(self):
        code, out, _ = self.run_cli(["rules", "--profile", "kostka_payne"])
        self.assertEqual(code, 0)
        self.assertIn("parallel_perfect", out)
        self.assertIn("transition rules", out)
        self.assertIn("leading_tone_outer_voices", out)

    def test_meter_is_accepted_and_ignored(self):
        """Same answer whatever the meter, because meter must not reach the rules."""
        _, four_four, _ = self.run_cli([
            "realize", "--key", "C major", "--meter", "4/4", "--progression", "I IV V I"])
        _, three_eight, _ = self.run_cli([
            "realize", "--key", "C major", "--meter", "3/8", "--progression", "I IV V I"])
        self.assertEqual(four_four, three_eight)

    def test_bad_numeral_exits_with_a_message(self):
        code, _, err = self.run_cli([
            "realize", "--key", "C major", "--progression", "I Xq7 V"])
        self.assertEqual(code, 2)
        self.assertIn("Xq7", err)


if __name__ == "__main__":
    unittest.main()
