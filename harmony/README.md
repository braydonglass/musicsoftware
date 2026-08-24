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

## Holding a melody in part

A melody may be pinned only where you want it pinned. `_` leaves that chord's
soprano to the engine:

```
$ harmony realize --key "C major" --progression "I IV V I" --soprano "E5 _ B4 C5"
```

A melody shorter than the progression says the same thing about the chords
past its end, which is what makes adding a chord safe. The engine picks a
soprano when it is given none, so a fifth numeral used to rewrite the whole
tune; now the four notes already chosen stay put and only the new chord is in
play.

The web page has a **Keep soprano** button for exactly this. Press it and the
realized soprano is written back into the melody box after every realization,
so a chord can be added, a profile changed or an alternate chosen without
losing the tune.

## Passing tones

A passing tone fills a melodic third with the step between. The engine does
not decide to write one: it reports every place one *would* go, and which of
those to take is the writer's. In the web page the offers are dotted rings in
the score — click one to place it, click the note to take it out.

Nothing is offered blind. Every candidate is run through the rules already in
the registry, and the refused ones stay on the page as dimmed rings that name
the rule when clicked, because where a passing tone cannot go is worth as much
as where one can. This is the classic trap: `E4/C4` moving to `G4/D4` is a
third opening to a fifth and is clean, but fill the soprano's third with `F4`
and the pair reads `C4/F4` to `D4/G4` — consecutive perfect fourths the chords
alone never had.

Only rules that can speak about a non-chord tone are consulted, which means
motion and position. The harmonic rules all ask what a *chord* owes, and a
passing tone is not in the chord, so `incomplete_chord`,
`missing_essential_tone`, `doubling_preference` and the resolution rules are
deliberately not asked. `core/embellish.py` lists both sets and says why each
is where it is.

Two passing tones that are each legal alone are not therefore legal together,
so choices are taken one at a time and each is judged against the sonority the
ones before it have already built.

The spelling falls out of the rules rather than out of new code. In C minor an
`A-flat` filling `G` up to `B-natural` is a melodic augmented second, and
`melodic_augmented` refuses it — the same rule that would refuse it anywhere
else.

**Meter still goes no further.** A passing tone sits on the weak half of the
beat it decorates, which is a fact about the beat and not about the bar, so
the embellishment pass is never given a time signature. The assertion that
`4/4` and `3/8` produce identical output holds with passing tones on.

Passing tones are a web-page feature. There is no `realize --embellish` flag:
placing them is something done by pointing at a score, and a command line is
the wrong instrument for it. The engine is `core/embellish.py` if that ever
changes.

## Chord vocabulary

| Kind | Examples |
|---|---|
| Diatonic triads, all inversions | `I ii iii IV V vi vii°`, `I6`, `V64` |
| Sevenths, all inversions | `V7 V65 V43 V42 ii7 IV7` |
| Diminished sevenths | `vii°7`, `viiø7` |
| Augmented triads | `III+`, `V+`, `I+` — the `+` raises the fifth |
| Borrowed from the parallel mode | `♭VI`, `♭III`, `♭VII` (plain `b` works too) |
| Secondary dominants | `V/V V7/V vii°7/V V/ii V/vi V7/IV` |
| Augmented sixths | `It+6 Fr+6 Ger+6` (also `It6`, `Ger65`, `Fr43`) |

A flat before the numeral lowers the root a semitone and keeps its letter:
the sixth degree of C is A, so `♭VI` is A-flat major and never G-sharp. That
is also why it is refused in a minor key, where the third, sixth and seventh
are lowered already and flattening one again would ask for a double flat.

A quality mark and a flat are both explicit requests for a tone outside the
key, so neither is put to the diatonic check that refuses a bare `vii` in C
major for needing an F-sharp.

Not implemented: the cadential six-four, and mixture beyond what a flat or a
quality mark asks for.

`I64` is refused on purpose. The cadential six-four is a dominant-function
chord wearing tonic clothing, and grading it properly needs a strong-beat
test — which requires meter, which is deliberately kept away from the rule
engine. Refusing it is better than getting it quietly wrong.

## Profiles

Rules are data. `profiles/*.json` decides which are enabled, at what
severity, and at what cost. No rule logic lives in a profile and no profile
value is hardcoded in a rule.

One profile ships: `strict`. The leading tone resolves in every voice, the
German sixth's fifths are refused, and hidden fifths, fourths and octaves are
policed in all six pairs whenever the upper voice leaps.

It used to be `kostka_payne`, and it carried that textbook's two leniencies:
a leading tone could be frustrated in an inner voice, and the German sixth's
fifths were permitted. Both were parameters, so removing them changed no rule
logic — which is the point of keeping rules as data.

One setting had to move the other way to make that work. `hidden_perfect_leap`
was `"none"`, meaning any similar approach to a perfect interval counted at
all — stricter than any textbook, and the rule's own comment says so. It
cannot be afforded. Under `"none"` seven of the twenty-four progressions in
the clean corpus stop being writable as typed, `I IV V I` among them: a
root-position `V` to `I` has no legal voicing left, and the solver quietly
re-voices the dominant as `V65` instead. It is `"upper"`, the classical
condition — the fault is the upper voice *leaping* into the perfect interval.
The profile still refuses more than the old one did: 6.67% of the transitions
in a two-key sweep survive it against 7.25% before.

That leaves the fourth, and the fourth needs its own answer. `IV` to `V` puts
a direct perfect fourth between some pair every time: the roots are a step
apart, so the upper voices are obliged to move together, and the voice on top
*steps* rather than leaps. Under `"upper"` nothing sees it.

Loosening `hidden_perfect_leap` is not the fix, and this is where one switch
for three intervals gives out. Set to `"none"` it also condemns the direct
octave in `V` to `I` — the soprano stepping 7 to 8 over a bass leaping 5 to 1
— which is the authentic cadence, and seven of the twenty-four corpus
progressions stop being writable.

So the fourth answers to `hidden_fourth_leap`, and the shipped profile sets it
to `"none"`: a direct fourth is a fault however it is approached, while fifths
and octaves keep the classical condition. The whole corpus still writes as
typed, and the landing page's `IV` to `V` comes out clean — the solver simply
chooses a different voicing, which was available the whole time.

The outer voices need the same treatment for the opposite interval.
`V` to `I` puts the soprano on 8 and the bass on 1, both rising, which is a
direct octave between the two voices a listener follows most — and the
classical excuse is that the soprano steps, which is exactly the excuse that
does not apply when nothing is hidden. `hidden_outer_leap` covers the outer
pair alone and also ships as `"none"`. That it is affordable depends entirely
on it being one pair: the same strictness across all six costs nine of the
twenty-four progressions, while here the cadence simply arrives by contrary
motion instead — the soprano falling to the tonic as the bass rises.

## Three voices moving together

The interval rules each judge one pair after the fact. `similar_motion` is
the one rule that looks at the texture instead, and it is preventive: when
three voices move the same way, some pair lands on a perfect fourth, fifth or
octave in similar motion about nine times in ten, and when all four do it is
certain. Measured across two keys:

| voices moving together | some pair reaches a perfect interval |
|---|---|
| 2 | 52.7% |
| 3 | 91.4% |
| 4 | 100% |

So it is priced, not forbidden — the remaining tenth really are clean, and
forbidding it outright costs three progressions in minor, where `iv` to `V`
leaves the upper voices nowhere else to go. `similar_motion_limit` sets how
many voices count as too many; the cost sits deliberately just below
`voice_unison`, because a unison collapses four parts into three and that is
a worse outcome than a texture which merely invites trouble.

`applied_leading_tone_voices` says the same thing for a secondary dominant's
applied leading tone, which `waiver_for` already excuses the fifth of.

Both are set to the soprano and the bass, which is where the rule is strictest
and where it belongs. The leading tone pulls a half step to the tonic and an
outer voice must take it. An inner voice may instead let it fall to the *fifth*
of the chord it was resolving into — 7 down to 5 — and only that: any other
leap away is a fault wherever it happens. The figure earns its place by
avoiding parallel fifths or keeping the resolving chord complete, which is
occasional rather than routine, so it carries a `waived_cost` and the search
reaches for it only where it must.

This was got wrong here once in the other direction. Holding the leading tone
in all four voices sounds stricter and reads stricter, and it costs six of the
twenty-four corpus progressions the moment direct intervals are policed
seriously — because the two constraints compete for the same room.

`harmony rules --profile NAME` prints what is active, which is the honest
way to answer what a profile does — a prose table describing one drifts from
the JSON the moment either is edited, and this one did.

To make another, copy the file and change what you want; anything dropped
falls back to the rule's registered default, and `--profile` also takes a
path, so a profile does not have to live in `profiles/` to be used.

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

So it is its own rule, `unequal_fifths`, which ships enabled and hard:

```json
"unequal_fifths": { "enabled": true, "severity": "error", "cost": "inf" }
```

Set `"enabled": false` for the permissive reading. The `unequal_fifths`
parameter takes `"all"` or `"with_bass"`, the latter narrowing it to pairs
involving the bass; the shipped profile uses `"all"`.

### And the same for fourths

`unequal_fourths` is the fourth's half of the same idea: a perfect fourth
moving to an augmented one, or back, with both voices moving. It is a
separate rule because neither of its neighbours can see it — `parallel_perfect`
requires *both* intervals to be perfect, and `hidden_perfect` requires the
*arrival* to be perfect. An augmented fourth is neither, so a fourth sliding
into a tritone went unreported by both.

That is easy to reach in minor. The diminished chord on the second degree
puts a tritone above its own third, so `i` to `ii°6` in D minor with the
soprano on `D5` and the tenor on `A3` writes `D5/A3` — a perfect fourth —
straight into `E5/Bb3`, a tritone. Two fourths on the staff, moving together.

It takes the same `"all"` or `"with_bass"` parameter as `unequal_fifths` and
consults the same waiver, so a diminished chord, a secondary dominant or an
augmented sixth excuses it for the same stated reason and it is reported as an
exception rather than a fault.

The augmented sixth belongs in that list for the reason the chord exists: both
of its outer tones are obliged to move outward by semitone at once, and
honouring them is what forces the fifth. Practice breaks the unequal fifth
there rather than leave a tendency tone hanging, and the chord it resolves into
inherits the same problem.

### And the case between them

Three rules divide this ground, and for a while they did not cover it.
`parallel_perfect` wants *both* intervals perfect. `unequal_fifths` and
`unequal_fourths` want *one* of each. Nothing wanted the same altered
interval twice — a diminished fifth to a diminished fifth, an augmented
fourth to an augmented fourth — so that combination passed unseen, and it is
easy to reach: the diminished chord on the second degree of a minor key
writes a pair of diminished fifths into `V7` without trying.

`parallel_altered` is that case. It does **not** consult the waiver, and the
waiver's own text is why: the excuse is for an interval whose *quality*
changes under a chord that commits every voice at once, and it says outright
that a genuine parallel fifth is still caught, because quality is stored
rather than counted. Two diminished fifths in a row are two fifths in a row.

Closing it cost nothing — every progression in the clean corpus still writes
as typed.

## What an excuse costs

A waived violation says "this is not a fault, and here is why". It used to
also say "and it costs nothing to prefer", which is a different claim and not
one anybody made on purpose. Left free, an excused edge and a clean edge cost
the same, so the search picked between them on other grounds — and an excuse
meant for the case where nothing else works was being taken where something
else worked perfectly well.

`waived_cost` is what a profile charges for its own excuse:

```json
"unequal_fifths": { "enabled": true, "severity": "error", "cost": "inf",
                    "waived_cost": 40 }
```

The edge stays legal, so nothing becomes unwritable and the violation is still
reported as an exception carrying its reason. It just gets expensive, which is
how this engine says *only where there is no alternative*. The shipped profile
prices `unequal_fifths`, `unequal_fourths`, `hidden_perfect` and
`parallel_perfect` at 40, well above any ordinary preference.

The effect is worth recording. Before pricing, realizing the clean corpus
produced three excused faults; after, it produces none — in every case a clean
voicing existed and the engine simply had no reason to prefer it. All
twenty-four progressions still write as typed.

`"waived_cost": "inf"` withdraws the excuse altogether, which is also how a
profile reaches the waivers in `waiver_for` that it could not otherwise touch.


## Preferences a profile may zero, and facts it may not

`root_doubling` and `incomplete_chord` are preferences: a profile may price
them at whatever it likes, including nothing. `missing_essential_tone` is
not. The third carries a chord's quality, the seventh its function, and a
dominant's third *is* the leading tone — so those are a hard rule no profile
can switch off, and only the fifth is ever expendable.

This distinction exists because it was got wrong once. A profile priced
chord completeness at zero, which quietly let the solver drop the third of V
and realize `i V i` in D minor with no C-sharp anywhere. A test now realizes
that progression under every profile on disk and looks for the leading
tone, so the next profile cannot reintroduce it.

## Known limits

- `leap_recovery` needs three chords, and a trellis edge may only depend on
  two. It is evaluated by `check` and skipped by the solver, so it is a
  style note rather than a search constraint.
- `check` grades chords, not decorations. A realization with passing tones in
  it cannot be submitted for grading: the voice lines would be longer than the
  progression, and every non-chord tone would be read as a chord tone and
  condemned.
- Passing tones only. Neighbours would take the same machinery, but
  suspensions and anticipations sit on the strong half of a beat, and knowing
  which half is strong needs meter - the same requirement that keeps `I64`
  out.
- The German sixth resolving straight to V produces parallel fifths in the
  obvious voicing, and the shipped profile refuses them
  (`german_sixth_fifths: "forbid"`). This constrains the voicing rather than
  forbidding the progression: `i iv Ger+6 V` in C minor still realizes
  cleanly, because the solver finds a spacing where the fifths do not arise.
  Set the parameter to `"allow"` to permit the ordinary voicing, and the
  fifths come back reported as an exception with the reason practice
  accepts them.
- `citation` is empty on every rule, deliberately. A wrong citation is worse
  than none, and the doubling defaults want checking against a specific
  edition before any of this text is shown to students.
