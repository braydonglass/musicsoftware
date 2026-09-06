# Prelude figuration

A Prelude button beside Play that redraws a realized progression as keyboard
figuration — sixteenth notes running through the chord instead of four voices
striking together. A form picker beside the button chooses the pattern. The
first form is the shape of Bach's Prelude in C, BWV 846.

The staff, playback and the exported MIDI all follow the figuration. There is
one implementation of each pattern, in Python, so the speakers and the file
cannot tell different stories.

## Why this needs a new note shape

`embellish.Event` is what `midi.timeline()` and the page's `sounding()` both
consume today. It carries a whole `Voicing` and a duration, which means every
event sounds all four voices at once. That is exactly wrong for an arpeggio,
which is monophonic: at any instant one note is being struck.

It is also short a note. Bach's figure in bar 1 is C3 E3 G3 C4 E4 — five
pitches over a four-voice chord. The E4 belongs to no voice. There is nowhere
in `Event` to put it.

Two alternatives were considered and rejected. Adding `silent: tuple[str, ...]`
to `Event` would carry three lies through `timeline()`, `sounding()` and the
renderer for every sixteenth, and still has no home for the E4. Building the
figure in JavaScript would mean two implementations of one rule, which drift.

So figuration gets its own flat note list, and the encoder learns to take one.

## The ladder

Every form is a pattern of indices into a ladder of pitches, ascending.

The ladder is built from the realization exactly as the solver wrote it. No
re-voicing. The chord you see in the block-chord view is the chord you hear
figurated, and this engine's voicings are wider than Bach's — a realization of
`I ii7 V7 I` in C spans 2.0 to 2.6 octaves against Bach's 1.4, so the figure
comes out as a broad spread rather than a compact keyboard texture. That is a
faithful report of what was written. Choosing `position: closed` narrows it;
that is the documented way to get closer to Bach.

Construction:

1. Take the four voices' pitches, drop duplicates by MIDI number, sort
   ascending. A voicing that doubles a pitch yields three rungs, not four.
   This is why the figure never stutters: a repeated pitch is one rung, and
   the pattern steps past it to a real note.
2. If the form needs more rungs than that, extend upward with the next chord
   tone above the current top, repeatedly, until there are enough.

The extension rule is one function:

```python
def above(pitch, spec):
    """The next pitch above, spelled from the chord's own pitch classes."""
    by_letter = {pc.letter: pc for pc in spec.pitch_classes}
    ladder = pitch.diatonic_index + 1
    while ladder < pitch.diatonic_index + 15:
        letter = ladder % 7
        if letter in by_letter:
            cand = Pitch(letter, ladder // 7, by_letter[letter].alteration)
            if cand.midi > pitch.midi:
                return cand
        ladder += 1
    raise ValueError(...)
```

It walks the letter ladder and takes the first letter the chord owns, spelled
with the chord's own accidental. Because `ChordSpec.pitch_classes` is spelled
rather than enharmonic, this is right on chromatic chords: over a German
augmented sixth (`Ab C Eb F#`) the note above F#4 is Ab4, not G#4. Over `N6`
(`Db F Ab`) the note above Db5 is F5. The `cand.midi > pitch.midi` guard
matters: above a soprano B#3 the answer is E4, skipping the C4 that shares its
MIDI number.

Checked against the real engine, the rule reproduces BWV 846 bars 1 to 3
exactly: over `I` above C4 it gives E4, over `ii7` above D4 it gives F4, over
`V7` above D4 it gives F4.

## `harmony/core/prelude.py`

A new module. Nothing else in `core` imports it.

```python
@dataclass(frozen=True)
class Note:
    pitch: Pitch
    start: float      # beats from the beginning of the piece
    beats: float      # how long it sounds
    chord: int        # index of the chord it came from, for highlighting
    rung: int         # which ladder rung, for the staff and for tests


@dataclass(frozen=True)
class Form:
    id: str
    label: str            # what the picker shows
    meter: tuple[int, int]
    unit: float           # beats per pattern step: 0.25 a sixteenth,
                          # 0.5 an eighth
    pattern: tuple        # per step, a rung or a tuple of rungs struck together
    sustained: tuple[int, ...]    # pattern positions whose note holds to the
                                  # end of the pattern instead of stopping
                                  # after one step
    drone: tuple[int, ...]        # rungs struck once at the start of the
                                  # measure and held for the whole measure,
                                  # outside the pattern
    rungs: int            # how tall the ladder must be
```

A step is one rung or several struck at once, and the second kind is what
separates an accompaniment from an arpeggio. A waltz's second and third beats
are a chord, not a note, and no reordering of single rungs produces one. On the
staff a step of several rungs is one column with one stem.

The pattern repeats `beats_per_measure / (unit * len(pattern))` times per
measure, which is a whole number for every form here.

One invariant, checked by a test: a form must not strike a rung while that
same rung is sounding as a sustain or a drone. Two overlapping notes of the
same MIDI number would have the second note-off silence the first, and the
encoder writes note-offs before note-ons at a shared tick.

`figurate(voicings, specs, form) -> list[Note]` walks the chords in order,
builds each ladder, emits one `Note` per pattern step, and advances `start` by
`form.unit`. One chord fills one measure; the pattern repeats within the
measure as many times as the meter needs.

`spans(notes) -> list[tuple[float, float, int]]` collapses the note list into
the `(start, end, midi)` triples the encoder already speaks.

### The forms

**`bach-c` — Bach, Prelude in C.** 4/4, sixteenths, five rungs. The pattern is
`(0, 1, 2, 3, 4, 2, 3, 4)`, eight steps, played twice per measure. On a
voicing of C3 E3 G3 C4 that is C3 E3 G3 C4 E4 G3 C4 E4, which is bar 1.

Pattern positions 0 and 1 are sustained: their notes hold to the end of the
eight-step group
rather than stopping after a sixteenth. That is what Bach writes — the two low
notes are held under the running figure — and it is the difference between the
prelude and a music box. The flat note list carries this for free, since
`beats` is independent of the grid.

We do not tie the held notes across the half-measure boundary the way the
engraving does; each group restrikes them. Noted as a v1 simplification.

**`alberti` — Alberti bass.** 4/4, eighths, four rungs. Rung 3, the top of
the voicing, is a drone: struck once at the start of the measure and held
through it as the melody note. The lower three run `(0, 2, 1, 2)`, twice per
measure.

**`waltz` — broken-chord waltz.** 3/4, eighths, four rungs. Pattern
`(0, 1, 2, 3, 2, 1)`, six steps, once per measure. No sustains, no drone.
This is the form that forces meter to stop being a constant.

Then nine more, in the same vocabulary:

| id | meter | shape |
|---|---|---|
| `rise-fall` | 4/4 | `(0,1,2,3,4,3,2,1)` sixteenths - Bach's rungs, turning back down |
| `harp` | 4/4 | `(0..7)` sixteenths over an eight-rung ladder, about three octaves |
| `moonlight` | 12/8 | `(1,2,3)` four times over a droned bass |
| `nocturne` | 6/8 | `(0,2,3,2,3,2)` with the bass sustained under it |
| `murky` | 4/4 | `(0,2,0,2)` eighths under a droned melody |
| `oompah` | 3/4 | `(0, (1,2,3), (1,2,3))` - bass, chord, chord |
| `stride` | 4/4 | `(0, (2,3), 1, (2,3))` - alternating bass answered by a chord |
| `boom-chick` | 2/4 | `(0, (1,2,3))` |
| `pulse` | 4/4 | `((1,2,3),)` eight times over a droned bass |

Twelve in all. The last four are the ones that need a step to strike several
rungs at once.

## Meter stops being fixed

`server.FIXED_METER = (4, 4)` is read in two places: the `meter` field of the
realize payload, and the `meter=` argument to `midi_bytes` in `midi_for`. The
waltz is in 3/4, so both become the selected form's meter, defaulting to 4/4
when no form is active. `midi.to_bytes` already writes whatever meter it is
handed into the time-signature bytes, so nothing changes there.

## The encoder

`midi.to_bytes` currently does `timeline(_as_events(items, beats_per_chord))`
and then schedules the resulting triples. The scheduling half is split out:

```python
def encode(spans, tempo_bpm=84.0, meter=(4, 4), velocity=72) -> bytes
```

`to_bytes` becomes a thin wrapper that computes the spans from voicings or
events and calls `encode`. The prelude path computes its spans from a note
list and calls the same `encode`. No duplicated byte-writing, and the existing
signature is unchanged so the CLI and `test_midi` are untouched.

## The web layer

`realize_payload` computes every form for every result and ships them all:

```json
"prelude": {
  "ladders": [[{"name": "C3", "midi": 48, "letter": 0, "octave": 3,
                "alteration": 0, "accidental": false}, ...], ...],
  "forms": {
    "bach-c": {"meter": "4/4", "beatsPerMeasure": 4.0, "unit": 0.25,
               "notes": [[0, 0, 0.0, 2.0], ...]},
    "moonlight": {...}
  }
}
```

Computed unconditionally rather than on demand, because figurating a solved
realization is arithmetic over a few hundred notes while re-solving is the
expensive thing. Pressing Prelude or changing the form is then instant and
costs no round trip - which matters, since the last performance complaint on
this project was about exactly that kind of latency.

A note is four numbers - chord, rung, start, length - not an object. What
pitch a rung is comes from `ladders`, one per chord, built as tall as the
tallest form needs and shared by all of them, because every form climbs the
same ladder. Spelled out per note per form, twelve forms ran past a megabyte
on a nine-chord progression with five alternates; this way the same payload is
under 300 KB, and no part of the figure moved into the page to buy that. The
page expands a form once, on first use, and keeps it.

`/api/midi` gains an optional `form` parameter. When present, `midi_for`
figurates before encoding and uses the form's meter. The filename stem gains
the form id.

`tools/build_static.py` needs no edit. It globs `harmony/**/*.py`, so the new
module is bundled automatically, and its Pyodide shim forwards the whole
request and params dicts verbatim, so both the new payload field and the new
`form` parameter pass through untouched. The build must still be re-run —
`docs/index.html` is a committed artifact and `test_static_build` compares it
against a fresh build.

## The staff

This is the bulk of the work, and it is a second renderer rather than a change
to the first.

`draw()` cannot be bent into this. Its horizontal layout is index-driven —
`x = LEFT + CLEF_W + sigCount * sigW + index * COL_W + COL_W / 2` — one column
per chord, with width growing unboundedly and nothing measuring the viewport.
It has one global vertical origin, `yOf(d) = (TOP_REF - d) * STEP`, with no
per-system transform anywhere. It has no beams, no flags, no rests, no time
signature digits, and no notehead glyph at all — every head is an inline
`<ellipse>`. Stem direction is per-voice and fixed by design, which is
meaningless for a monophonic figure.

So: `drawPrelude(payload, resultIndex, formId)`, beside `draw()`, sharing
`el`, `line`, `glyph`, `dia`, `yOf`, `ledgersFor`, `accKind` and the accidental
widths. When the prelude is on it renders; when off, `draw()` renders as now.

Layout:

- One measure per chord. Horizontal position is time-driven, not index-driven.
  How wide a measure has to be is a question about how many times something is
  struck in it, not how many beats it has - twelve slow eighths need more room
  than three quarters, and paying out pixels per beat gives the sparse measure
  the wider one. The width is `max(busiest column count * 19.5, beats * 46)`
  and the notes are spread across it, which puts a sixteenth at about 18px
  against a notehead 14.8px wide.
- Notes struck at the same instant are one column with one stem, taken from
  the lowest head and passing all of them. Two heads a step apart move to
  opposite sides of the stem.
- The number of measures per system is
  `floor((container width - clef - key signature - time signature) / measure width)`,
  at least one, measured from `score.parentNode.clientWidth` and recomputed on
  a debounced resize. The time signature's width is reserved on every system
  though only the first prints it, so bars line up down the page.
- Each system is a `<g transform="translate(0, dy)">`. That is how wrapping
  gets done without touching `yOf`'s single origin: the coordinate maths stays
  identical inside each group and the group is moved. Every system gets the
  same height, taken from the whole piece, so the gap between lines does not
  breathe as the music moves.
- Clef and key signature are drawn at the start of every system.
- A barline between measures and at the end of each system. `draw()` has
  exactly two vertical rules today, both outside any loop; the prelude view
  needs them per measure, which is new code, not a reuse.
- **There is no staff assignment to make.** `yOf` has a single origin for the
  whole grand staff, so a pitch sits where it sits and no note is ever "put
  on" the treble or the bass staff. Ledger lines come from the existing
  `ledgersFor`, which already knows the two-space gap between the staves.
- Beam groups are one beat of the figure, and are not broken where the figure
  crosses between the staves — they could hardly be, given the point above,
  and Bach beams the G below middle C with the two notes above it for the
  same reason. Sixteenths get two beam lines, eighths one.
- Stems on the figure always go up, so the beam rides over the run rather than
  through the chord it is unfolding. A held note takes the ordinary rule — up
  from below middle C, down from above — which also keeps it clear of the
  beam. This diverges from `draw()`'s fixed per-voice rule, which exists there
  to disambiguate two voices sharing a line and has nothing to disambiguate in
  a single running line.
- Beams are slanted, following the run, because a flat beam over a two-octave
  arpeggio leaves the lowest note on a stem half the height of the staff. The
  slant is capped at three staff spaces, and the whole beam is then lifted
  until the shortest stem clears 22px. A group of one gets a 13px stub off its
  stem, which says what a flag would and needs no glyph.
- A held note is drawn with an open head. It is the only duration distinction
  on the page — there is no half-note glyph and no augmentation dot — and it
  is enough to read the note as long.
- Time signature: `<text>` digits, not path glyphs. There is no digit glyph in
  the file and `<text>` is already used for voice names, so this adds no new
  path data. It is drawn once, on the first system.
- Highlighting on playback stays per chord, which is now per measure.
- Below about 460px of window the view can no longer wrap — one bar of
  sixteenths is already wider than that — so sideways scrolling stays
  available as a floor rather than being clipped away.

## Playback

`play()` takes its notes from `sounding(events)` today. When the prelude is on
it reads the prelude note list straight out of the payload — already flat,
already carrying `start` and `beats`, so no `sounding()` equivalent is needed
and there is no second scheduling rule to keep in step. The chord highlight is
scheduled at each measure's first note.

Voice mute and solo do not apply to a figure that has no voices, so those
controls are ignored while the prelude is on.

## The controls

A `Prelude` toggle button in `.transport`, after `Play`, and a `<select>` of
the three forms beside it. Both are disabled until a realization exists. The
form picker is hidden while the prelude is off.

Turning the prelude on switches the staff, playback and the export target.
Turning it off restores all three. The state is client-side only; it never
triggers a re-solve.

## Testing

`harmony/tests/test_prelude.py`, new:

- `bach-c` over a C3 E3 G3 C4 realization of `I` in C major emits exactly
  C3 E3 G3 C4 E4 G3 C4 E4, twice, and the two low notes sustain.
- The ladder extension spells chromatics correctly: `ii7` above D4 gives F4,
  `Ger+6` above F#4 gives Ab4, `N6` above Db5 gives F5, `vii°7` above Ab4
  gives B4, and above B#3 it gives E4.
- A voicing that doubles a pitch produces a ladder of distinct pitches, and
  the emitted measure contains no two consecutive identical MIDI numbers.
- No form strikes a rung while that rung is already sounding as a sustain or
  a drone, over every chord in the vocabulary.
- Every measure's durations sum to the meter.

`test_midi.py`: a prelude note list through `encode` yields the right tick
count, and `waltz` writes 3/4 into the time-signature bytes.

`test_web.py`: `/api/realize` carries a `prelude` block with every form and a
ladder per chord; each of the four numbers in a note resolves; every form
exports a file whose time signature matches its meter; and a nine-chord
progression with five alternates stays under 400 KB.

`test_static_build.py` passes after `python3 tools/build_static.py`.

## Not in v1

Free-text pattern editing. Per-measure form changes. Ties across the
half-measure as Bach engraves them. Repeats, pedal marks, dynamics. A tempo
that varies with the form. Figuration of embellished events — the prelude
reads the block voicings, not the decorated ones, and the Embellishments
toggle has no effect while it is on.

## Transport

Play, pause and stop, drawn as paths rather than typed as Unicode characters,
which render as colour emoji on most systems and cannot take the colour the
button is in.

Stop needed a fix that was not about the prelude at all. Every note of a run
is handed to the audio graph the moment Play is pressed, scheduled minutes
ahead if the piece is long, so clearing the timers stopped the highlight
moving and nothing else - the sound kept arriving. Each run now passes through
its own gain node, and stopping ramps that to zero over 40ms and disconnects
it.

Pause holds its place in beats and Play resumes from there. A note the resume
lands inside starts at once and runs out its remainder rather than being
dropped, so a held bass does not vanish for the rest of the measure it is
resumed into, and that measure is lit immediately instead of at the next one.
Pausing on the final note counts as finishing, not pausing.

Anything that changes the music underneath a held place - a re-realization, a
different alternate, turning the prelude on or off - stops rather than pauses.

The three staff toggles and the prelude are disabled until a realization
exists, and go out with it: there is nothing to decorate, measure or figurate
before there are chords.
