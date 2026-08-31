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
from harmony.core.checker import check, errors_only, explained_breaks
from harmony.core.key import Key
from harmony.core.roman import parse_progression
from harmony.core.rules.registry import PROFILE_DIR, Profile
from harmony.core.solver import NoRealization, realize, solve
from harmony.core.voice import VOICE_NAMES, Voicing
from harmony.core.pitch import Pitch


def voicing(s, a, t, b):
    return Voicing(*(Pitch.parse(p) for p in (s, a, t, b)))

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
        self.profile = Profile.load("strict")

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

    def test_the_registry_and_the_profiles_agree(self):
        """A rule that vanishes from the module must not vanish silently.

        Profile.rules() walks the registry, so a profile naming a rule that
        no longer exists is ignored without a word - the rule simply stops
        being enforced and every test that does not target it keeps passing.
        Editing this package by replacing a span of transition.py has now
        deleted a rule twice, so the two lists are pinned against each other.
        """
        from harmony.core.rules.registry import REGISTRY
        for name in shipped_profiles():
            with self.subTest(profile=name):
                configured = set(Profile.load(name).settings)
                self.assertEqual(
                    configured - set(REGISTRY), set(),
                    f"{name}.json configures rules that no longer exist")
                self.assertEqual(
                    set(REGISTRY) - configured, set(),
                    f"{name}.json says nothing about these registered rules")

    def test_reinversion_rescues_what_it_can(self):
        """iv -> V in minor survives only by re-voicing, and says so.

        The test used to be that writing it as asked had no answer at all.
        Now that the motion rules are priced rather than absolute it has one,
        and the thing worth checking is that the answer is bad: re-voicing
        exists to turn a faulty realization into a clean one, so the faulty
        one has to be there to be turned.
        """
        # V6 puts the leading tone in the bass, so the next bass must be the
        # tonic. IV cannot supply it; IV6 can.
        key = Key.parse("C major")
        specs = parse_progression("I V6 IV", key)
        as_written = realize(specs, key, self.profile)[0]
        self.assertNotEqual(
            errors_only(check(as_written.voicings, specs, key, self.profile)), [],
            "writing it as asked should still be faulty; nothing to rescue")
        result = solve(specs, key, self.profile)[0]    # with re-voicing allowed
        swaps = result.substitutions(specs)
        self.assertTrue(swaps, "it should report what it changed")
        self.assertFalse(any(u.endswith("64") for _, _, u in swaps),
                         "a six-four is not a general-purpose substitute")

    def test_a_progression_that_cannot_be_written_cleanly_says_what_it_broke(self):
        """Every chord can follow every chord. What it cost has to be said.

        This used to check that the engine refused the progression and named
        the rule in the refusal. It no longer refuses anything - the motion
        rules are priced, so there is always an answer - and the same
        obligation lands on the report instead: the answer comes back with
        its faults named, rather than looking like a clean one.
        """
        key = Key.parse("C major")
        specs = parse_progression("I V6 I6 IV", key)
        result = solve(specs, key, self.profile)[0]
        faults = errors_only(check(result.voicings, result.specs or specs,
                                   key, self.profile))
        self.assertNotEqual(faults, [], "it came back looking clean")
        named = " ".join(f.rule_id for f in faults)
        self.assertTrue(
            any(word in named for word in
                ("leading_tone", "hidden_perfect", "parallel", "unequal")),
            f"the faults should name what went wrong: {named}")


class TheSeventhThatStopsBeingADissonance(unittest.TestCase):
    """V7 -> iv, and why the seventh does not have to move.

    A seventh resolves downward because it is dissonant against its own
    root. In every minor key the seventh of V7 is the root of iv, so the
    chord that follows makes it a consonance and there is nothing left to
    resolve. Without this the progression is unwritable, and the engine used
    to escape by quietly dropping the seventh out of a chord the writer had
    figured as a seventh chord.
    """

    PROGRESSION = "V V43 iv i V7 VI VI V i"
    MINOR_KEYS = ["c", "a", "e", "b", "f#", "c#", "g#", "d#",
                  "d", "g", "f", "bb", "eb", "ab"]

    def setUp(self):
        self.profile = Profile.load("strict")

    def test_the_seventh_of_V7_is_a_chord_tone_of_iv_in_every_minor_key(self):
        """The fact the exception rests on, checked rather than assumed."""
        for tonic in self.MINOR_KEYS:
            with self.subTest(key=tonic):
                key = Key.parse(f"{tonic} minor")
                dominant, subdominant = parse_progression("V7 iv", key)
                self.assertIn(dominant.seventh_pc, subdominant.pitch_classes)

    def test_it_realizes_in_every_minor_key(self):
        for tonic in self.MINOR_KEYS:
            with self.subTest(key=tonic):
                key = Key.parse(f"{tonic} minor")
                specs = parse_progression(self.PROGRESSION, key)
                result = solve(specs, key, self.profile)[0]
                errors = errors_only(
                    check(result.voicings, result.specs or specs, key, self.profile))
                self.assertEqual(errors, [], [str(e) for e in errors])

    def test_a_figured_seventh_chord_keeps_its_seventh(self):
        """V43 names a seventh chord; one without a seventh is a different chord."""
        for tonic in self.MINOR_KEYS:
            with self.subTest(key=tonic):
                key = Key.parse(f"{tonic} minor")
                specs = parse_progression(self.PROGRESSION, key)
                result = solve(specs, key, self.profile)[0]
                spec = (result.specs or specs)[1]
                self.assertIsNotNone(spec.seventh_pc)
                self.assertIn(
                    spec.seventh_pc,
                    [p.pitch_class for p in result.voicings[1].pitches],
                    f"{spec.numeral} was written without its seventh")

    def test_holding_it_is_reported_with_the_reason(self):
        """The student meets the rule and its exception together."""
        key = Key.parse("c minor")
        specs = parse_progression(self.PROGRESSION, key)
        result = solve(specs, key, self.profile)[0]
        graded = check(result.voicings, result.specs or specs, key, self.profile)
        held = [v for v in explained_breaks(graded)
                if v.rule_id == "seventh_resolution"]
        self.assertTrue(held, "the held seventh went unexplained")
        self.assertIn("iv", held[0].reason)

    def test_a_seventh_still_has_to_resolve_when_it_stays_dissonant(self):
        """The exception is about consonance, not a general licence to hold."""
        key = Key.parse("C major")
        specs = parse_progression("V7 I", key)
        # the soprano keeps F4, the seventh, which I does not contain
        voicings = [voicing("F4", "D4", "B3", "G2"),
                    voicing("F4", "C4", "C4", "C3")]
        found = check(voicings, specs, key, self.profile)
        faults = [v for v in errors_only(found) if v.rule_id == "seventh_resolution"]
        self.assertTrue(faults, "an unresolved seventh was let through")


class NoPerfectIntervalSurvives(unittest.TestCase):
    """No parallel or direct octave, fifth or fourth. Anywhere. Ever.

    Deliberately computed from MIDI numbers rather than by asking the
    rules. A test written on top of interval_between and the rule helpers
    can only ever confirm that the rules agree with themselves, and that
    has already gone wrong here: an audit of unequal_fifths shared the
    exact blind spot of the rule it was auditing, because both looked only
    at intervals that arrive perfect. Counting semitones by hand has no
    opinion to share with the code it is checking.

    The perfect fourth counts. It is a fifth turned upside down, so a pair
    of them is a pair of fifths wearing a different hat.
    """

    PERFECT = {0: "octave", 7: "fifth", 5: "fourth"}

    def offences(self, voicings):
        out = []
        for i in range(len(voicings) - 1):
            here, there = voicings[i], voicings[i + 1]
            for a in range(4):
                for b in range(a + 1, 4):
                    upper, lower = VOICE_NAMES[a], VOICE_NAMES[b]
                    was = here[upper].midi - here[lower].midi
                    now = there[upper].midi - there[lower].midi
                    if now % 12 not in self.PERFECT:
                        continue
                    up = there[upper].midi - here[upper].midi
                    down = there[lower].midi - here[lower].midi
                    if not ((up > 0 and down > 0) or (up < 0 and down < 0)):
                        continue          # contrary or oblique: not this fault
                    out.append(
                        f"chord {i + 1}->{i + 2} "
                        f"{'parallel' if was == now else 'direct'} "
                        f"{self.PERFECT[now % 12]} between {upper} and {lower}: "
                        f"{here[upper]}/{here[lower]} -> {there[upper]}/{there[lower]}")
        return out

    def test_the_whole_corpus_is_free_of_them(self):
        profile = Profile.load("strict")
        for key_text, progression in CLEAN_CORPUS + [("C major", "I V/V V I")]:
            with self.subTest(key=key_text, progression=progression):
                key = Key.parse(key_text)
                specs = parse_progression(progression, key)
                for rank, result in enumerate(solve(specs, key, profile, k=3)):
                    found = self.offences(result.voicings)
                    self.assertEqual(
                        found, [],
                        f"{key_text} {progression} (alternate {rank + 1}): "
                        + "; ".join(found))

    def test_a_secondary_dominant_gets_re_voiced_rather_than_excused(self):
        """I V/V V I: the bass rises to G under a soprano rising to G.

        The applied leading tone F# has to go up, so if the bass takes the
        root of V the outer voices arrive at an octave in similar motion -
        a direct octave in the two most exposed parts. It used to be waived
        on the grounds that a secondary dominant's tendency tones leave no
        choice. There is a choice: put the third in the bass and it walks
        down to B while the soprano walks up.
        """
        key = Key.parse("C major")
        specs = parse_progression("I V/V V I", key)
        profile = Profile.load("strict")
        result = solve(specs, key, profile)[0]
        swapped = [used for _, written, used in result.substitutions(specs)
                   if written == "V"]
        self.assertTrue(swapped, "V was left in root position")
        self.assertIn(swapped[0], ("V6", "V65"), swapped[0])
        self.assertEqual(self.offences(result.voicings), [])

    def test_doubling_is_still_negotiable(self):
        """The motion rules got stricter; the doubling rules did not.

        That is the trade being made - a doubling that has to be explained
        is a better outcome than a perfect interval that has to be excused.
        """
        key = Key.parse("C major")
        specs = parse_progression("I V/V V I", key)
        profile = Profile.load("strict")
        result = solve(specs, key, profile)[0]
        graded = check(result.voicings, result.specs or specs, key, profile)
        self.assertEqual(errors_only(graded), [])
        kinds = {v.rule_id for v in explained_breaks(graded)}
        self.assertIn("doubled_leading_tone", kinds,
                      "the doubling waiver should still be doing the work")


class TheQualitySurvivesTheDoubling(unittest.TestCase):
    """Doubling is negotiable. What the chord *is* never was.

    The rule that a chord keeps its root and its third let go of the fifth
    in every case, which is right for a perfect fifth - it says nothing the
    root has not already said, and dropping it to double the root is how an
    incomplete triad is written. It is wrong for an altered one. V+ came
    back as G G G B: the root tripled, the augmented fifth gone, and
    nothing left that is augmented about it. That is a major chord with the
    wrong name on it, not a doubling choice.
    """

    ALTERED = [
        ("C major", "I V+ vi IV", 1),
        ("C major", "I III+ vi IV", 1),
        ("a minor", "i III+ iv V i", 1),
        ("C major", "I vii°7 I IV", 1),
        ("a minor", "i iv vii°7 i", 2),
    ]

    def test_an_altered_fifth_is_never_the_tone_that_gets_dropped(self):
        profile = Profile.load("strict")
        for key_text, progression, index in self.ALTERED:
            with self.subTest(progression=progression):
                key = Key.parse(key_text)
                specs = parse_progression(progression, key)
                result = solve(specs, key, profile)[0]
                spec = (result.specs or specs)[index]
                sounding = {str(result.voicings[index][name].pitch_class)
                            for name in VOICE_NAMES}
                for pc in spec.pitch_classes:
                    self.assertIn(
                        str(pc), sounding,
                        f"{spec.numeral} was written without its {pc}: "
                        f"{sorted(sounding)}")

    def test_a_perfect_fifth_may_still_be_dropped(self):
        """The permission that made the bug possible is still wanted.

        An incomplete triad - root doubled, fifth omitted - is ordinary
        practice, and tightening the altered case must not have taken it
        away.
        """
        from harmony.core.rules.registry import REGISTRY, StateContext
        from harmony.core.voicing import generate
        key = Key.parse("C major")
        profile = Profile.load("strict")
        spec = parse_progression("I", key)[0]
        rule = REGISTRY["missing_essential_tone"]
        # generate() hands back (voicing, cost) pairs
        incomplete = [v for v, _ in generate(spec, key, profile)
                      if len({v[name].pitch_class.chroma
                              for name in VOICE_NAMES}) == 2]
        self.assertTrue(incomplete, "no incomplete triad was generated at all")
        for voicing in incomplete[:5]:
            ctx = StateContext(voicing=voicing, spec=spec, key=key, index=0,
                               profile=profile)
            self.assertEqual(rule.check(ctx), [],
                             "a plain triad may omit its perfect fifth")


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
        code, out, _ = self.run_cli(["rules", "--profile", "strict"])
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


class ThePriceOfStrictness(unittest.TestCase):
    """What refusing every direct interval costs, recorded rather than hidden.

    solve() falls back to re-voicing when a progression has no answer as
    written, so the clean-corpus test above stays green while the engine
    quietly substitutes chords. That is the designed behaviour, and it is
    also how a real loss of capability disappears from a test suite. This
    uses realize(), which does not fall back, so the cost is written down
    and any change to it has to be looked at on purpose.
    """

    # Not "has no answer" any more - everything has one. These are the
    # progressions whose answer, written exactly as asked, has a fault in it
    # and needs re-voicing to come out clean.
    FAULTY_AS_TYPED = {
        ("C major", "I IV V I"),
        ("C major", "I vi IV V I"),
        ("C major", "I V/V V I"),
        ("C major", "I V7/IV IV V I"),
        ("C major", "I V/vi vi IV V I"),
        ("a minor", "i iv V i"),
        ("a minor", "i VI iv V i"),
        ("c minor", "i VI iv V i"),
    }

    def test_the_price_of_refusing_every_direct_interval(self):
        from harmony.core.solver import realize
        profile = Profile.load("strict")
        faulty = set()
        for key_text, progression in CLEAN_CORPUS:
            key = Key.parse(key_text)
            specs = parse_progression(progression, key)
            result = realize(specs, key, profile)[0]
            if errors_only(check(result.voicings, specs, key, profile)):
                faulty.add((key_text, progression))
        self.assertEqual(
            faulty, self.FAULTY_AS_TYPED,
            "the set of progressions this profile cannot write cleanly as typed "
            "has changed; if that was on purpose, update FAULTY_AS_TYPED and "
            "say why")

    def test_what_cannot_be_written_is_still_answered(self):
        """A refusal is not a crash: solve() re-voices, and says that it did."""
        key = Key.parse("C major")
        specs = parse_progression("I IV V I", key)
        profile = Profile.load("strict")
        result = solve(specs, key, profile)[0]
        self.assertTrue(result.substitutions(specs),
                        "the engine substituted nothing and said nothing")
        self.assertEqual(len(result.voicings), len(specs))
