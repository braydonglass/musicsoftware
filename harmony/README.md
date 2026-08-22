# harmony

Writes and grades four-part (SATB) chorale realizations from a key, a meter
and a sequence of Roman numerals.

```
$ python3 -m harmony realize --key "C major" --meter 4/4 --progression "I IV V I"
        1     2     3     4
  S:   G4    A4    G4    E4
  A:   C4    C4    B3    G3
  T:   E3    F3    D3    C3
  B:   C3    F2    G2    C3
        I     IV    V     I
  no violations
```

Run from this directory (the package's parent), or put it on `PYTHONPATH`.
No dependencies; tests run on stdlib `unittest`.

```
python3 -m unittest discover -s harmony/tests -t .
```

## Commands

```
harmony realize --key KEY [--meter M] --progression "I IV V I"
                [--profile NAME] [--alternates N] [--format grid|json|midi] [--out FILE]

harmony check   --key KEY --progression "I ii"
                --soprano "G4 A4" --alto "G3 D4" --tenor "E3 D3" --bass "C3 D3"
                [--profile NAME] [--include-style]

harmony chords  --key KEY --soprano "E5 F5 D5 C5"

harmony rules   [--profile NAME]
```

`check` exits 0 when clean and 1 when it finds a fault, so it drops into a
script without parsing its output.

## Harmonizing a melody

Give `realize` a `--soprano` and the melody is pinned; the engine fills in
alto, tenor and bass beneath it.

```
$ harmony realize --key "C major" --progression "I IV V7 I" --soprano "E5 F5 D5 C5"
```

`harmony chords` answers the other half — which chords could carry each note:

```
$ harmony chords --key "C major" --soprano "E5 F5 D5 C5"
  1. E5
       I        C E G            bass C    tonic
       I6       C E G            bass E    tonic
       iii      E G B            bass E    tonic
       ...
```

A chord is only offered if some legal voicing actually puts that note in the
soprano. Containing the pitch class is not enough — the note may sit outside
the soprano range, or every voicing reaching it may double a tendency tone.
The web page shows the same options as clickable chips under each note.

## Chord vocabulary

| Kind | Examples |
|---|---|
| Diatonic triads, all inversions | `I ii iii IV V vi vii°`, `I6`, `V64` |
| Sevenths, all inversions | `V7 V65 V43 V42 ii7 IV7` |
| Diminished sevenths | `vii°7`, `viiø7` |
| Secondary dominants | `V/V V7/V vii°7/V V/ii V/vi V7/IV` |
| Augmented sixths | `It+6 Fr+6 Ger+6` (also `It6`, `Ger65`, `Fr43`) |

Not implemented: the Neapolitan, the cadential six-four, and modal mixture
beyond what an explicit quality mark requests.

`I64` is refused on purpose. The cadential six-four is a dominant-function
chord wearing tonic clothing, and grading it properly needs a strong-beat
test — which requires meter, which is deliberately kept away from the rule
engine. Refusing it is better than getting it quietly wrong.

## Profiles

Rules are data. `profiles/*.json` decides which are enabled, at what
severity, and at what cost. No rule logic lives in a profile and no profile
value is hardcoded in a rule.

| Profile | Character |
|---|---|
| `kostka_payne` | Default. Inner-voice leading tones may be frustrated; hidden fifths policed between outer voices only. |
| `strict_pedagogical` | Leading tones always resolve; hidden fifths policed in all six pairs; unequal fifths (d5 to P5) refused. |
| `linear` | Doubling preference zeroed, voice-leading costs raised. Approximates Aldwell/Schachter. |

`harmony rules --profile NAME` prints what is active.

## Design commitments

**Pitch is stored spelled** — letter, octave, alteration. MIDI is derived.
Storing MIDI collapses F♯ into G♭, and about half the rules exist to tell
those apart. The German sixth in E♭ major spells C♭–E♭–G♭–A; collapse C♭
into B and the augmented sixth stops being an augmented sixth.

**Every interval carries two sizes** — generic (letter distance) and
specific (semitones). Quality falls out of crossing them. This is the only
reason a legal `d5 → P5` can be told from illegal parallel fifths, and
`test_rules_broken.py` asserts exactly that.

**Rules are data in one registry.** `realize` searches for an answer and
`check` grades one, and both call the same functions. The strongest test in
the suite realizes a progression and then asks the engine to grade its own
output, expecting silence; it fails the moment the two modes drift apart.

**Meter is stored and goes no further.** It never reaches the voicing
generator or the solver. A test asserts that `--meter 4/4` and `--meter 3/8`
produce byte-identical output.

## Unequal fifths

A diminished fifth moving to a perfect fifth is **not** parallel fifths — the
intervals differ in quality, and telling them apart is the whole reason pitch
is stored spelled. But it is not nothing either, and textbooks split on it:
`P5 -> d5` is universally accepted, `d5 -> P5` less so, and many texts refuse
it only when the bass is one of the two voices.

So it is the `unequal_fifths` rule, off by default. To catch it:

```json
"unequal_fifths": { "enabled": true, "severity": "error", "cost": "inf" }
```

The `unequal_fifths` parameter takes `"all"` or `"with_bass"`, the latter
narrowing it to pairs involving the bass. `strict_pedagogical` has it on and
set to `"all"`.

## Preferences a profile may zero, and facts it may not

`root_doubling` and `incomplete_chord` are preferences: a profile may price
them at whatever it likes, including nothing. `missing_essential_tone` is
not. The third carries a chord's quality, the seventh its function, and a
dominant's third *is* the leading tone — so those are a hard rule no profile
can switch off, and only the fifth is ever expendable.

This distinction exists because it was got wrong once. `linear` priced chord
completeness at zero, which quietly let the solver drop the third of V and
realize `i V i` in D minor with no C-sharp anywhere.

## Known limits

- `leap_recovery` needs three chords, and a trellis edge may only depend on
  two. It is evaluated by `check` and skipped by the solver, so it is a
  style note rather than a search constraint.
- The German sixth resolving straight to V produces parallel fifths.
  `kostka_payne` and `linear` permit them, `strict_pedagogical` refuses
  them; textbooks that refuse them expect a cadential six-four in between,
  which is not implemented.
- `citation` is empty on every rule, deliberately. A wrong citation is worse
  than none, and the doubling defaults want checking against a specific
  edition before any of this text is shown to students.
