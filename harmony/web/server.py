"""A thin HTTP layer over the engine.

Stdlib only, to keep the package dependency-free. Swapping in Flask would
touch this file and nothing else.

No rule logic lives here. This module parses a request, calls the same
functions the CLI calls, and serialises what comes back. Meter is 4/4 for a
plain realization and never shown, because the engine stores it and the rules
never see it; a prelude form carries its own, since a waltz is in three.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..version import RELEASED, VERSION
from ..core.checker import check, errors_only, explained_breaks
from ..core.embellish import apply as place_figures
from ..core.embellish import opportunities
from ..core.key import Key
from ..core.melody import (HOLE, candidates_for, parse_soprano, suggest,
                           transpose, vocabulary_for, workable)
from ..core.midi import encode as midi_encode
from ..core.midi import to_bytes as midi_bytes
from ..core.prelude import BY_ID as PRELUDE_FORMS
from ..core.prelude import FORMS as PRELUDE_FORM_LIST
from ..core.prelude import figurate, ladder_for
from ..core.prelude import spans as prelude_spans
from ..core.roman import RomanNumeralError, parse_progression
from ..core.roman import parse as parse_roman
from ..core.rules.registry import PROFILE_DIR, Profile
from ..core.rules.state import position_of
from ..core.solver import NoRealization, solve
from ..core.voice import VOICE_NAMES

STATIC = Path(__file__).resolve().parent / "static"
CORE = Path(__file__).resolve().parents[1] / "core"


def _build_stamp() -> str:
    """Newest mtime across the engine, so a stale server shows its age."""
    import datetime
    newest = max(p.stat().st_mtime for p in CORE.rglob("*.py"))
    return datetime.datetime.fromtimestamp(newest).strftime("%H:%M:%S")
DEFAULT_METER = (4, 4)


# One ladder serves every form, so it is built as tall as the tallest needs.
PRELUDE_RUNGS = max(form.rungs for form in PRELUDE_FORM_LIST)


def _meter_for(form_id: str | None) -> tuple[int, int]:
    form = PRELUDE_FORMS.get(form_id or "")
    return form.meter if form else DEFAULT_METER


def _note(pitch, key) -> dict:
    """A pitch in the shape the page draws from.

    Only notes departing from the key signature get a written accidental;
    the signature carries the rest.
    """
    return {"name": str(pitch), "midi": pitch.midi, "letter": pitch.letter,
            "octave": pitch.octave, "alteration": pitch.alteration,
            "accidental": key.is_altered(pitch)}


def candidates_payload(request: dict) -> dict:
    """Which chords could carry each note of a melody.

    A hole - a note the writer left for the engine - has no options to
    offer and is passed straight through, so a partly pinned melody does
    not break the chord chips underneath it.

    Whatever is already written is offered too. The teaching vocabulary is
    a starting list for an empty progression, not a fence around one that
    exists: a writer who typed V+ and then held the soprano was shown no V+
    to hold on to, and the chord silently became I. Under a D-sharp there
    was nothing on offer at all.
    """
    key = Key.parse(request.get("key", "C major"))
    profile = Profile.load(request.get("profile", "strict"))
    melody = parse_soprano(request.get("soprano", ""))

    vocabulary = list(vocabulary_for(key))
    for token in (request.get("progression") or "").split():
        if token in vocabulary:
            continue
        try:
            parse_roman(token, key)          # only what the key can spell
        except (RomanNumeralError, ValueError):
            continue
        vocabulary.append(token)
    # candidates_for, workable and suggest below all end up asking generate()
    # the same (note index, chord) question - each only ever narrows what
    # the one before it already searched - so one cache threaded through all
    # three means each later call reuses that work instead of redoing it.
    voicing_cache: dict = {}
    found = [candidates_for(note, key, profile, vocabulary, index=i, cache=voicing_cache)
             if note is not None else []
             for i, note in enumerate(melody)]

    # Then drop the ones that cannot be joined to their neighbours. Carrying
    # the note is only half of what a chord has to do, and a button that
    # errors when pressed is worse than no button - see workable().
    usable = workable([[o["numeral"] for o in options] for options in found],
                      melody, key, profile, cache=voicing_cache)
    found = [[o for o in options if o["numeral"] in keep]
             for options, keep in zip(found, usable)]

    notes = [
        {"note": str(note) if note is not None else HOLE,
         "free": note is None,
         "options": options}
        for note, options in zip(melody, found)
    ]
    # One chord per note, chosen across the phrase rather than one note at a
    # time - see suggest(). The page uses it wherever nothing is written.
    return {
        "ok": True,
        "suggested": suggest([[o["numeral"] for o in n["options"]] for n in notes],
                             key, melody, profile, cache=voicing_cache),
        "notes": notes,
    }


def transpose_payload(request: dict) -> dict:
    """The same melody on the same scale degrees of another key.

    Kept in the engine rather than done in the page. The page would have to
    grow its own idea of what a scale degree is and how a key spells one,
    and that copy would drift from this one - which is the reason the solver
    and the checker share their rules rather than each having a set.
    """
    from_key = Key.parse(request.get("from", "C major"))
    to_key = Key.parse(request.get("to", "C major"))
    profile = Profile.load(request.get("profile", "strict"))
    melody = parse_soprano(request.get("soprano", ""))
    low, high = profile.ranges["soprano"]
    moved = transpose(melody, from_key, to_key, low, high)
    return {"ok": True,
            "soprano": " ".join(HOLE if p is None else str(p) for p in moved)}


def parse_figures(text: str) -> list[str]:
    """Read the page's list of chosen figures from a URL.

    Each one is a slot as Opportunity.slot writes it - chord, voice, kind
    and note joined by colons - and they are separated by commas. Nothing
    is validated here; apply() rebuilds the candidates and refuses whatever
    no longer fits, which is what a stale or hand-edited URL deserves.
    """
    return [token.strip() for token in text.split(",") if token.strip()]


def midi_for(params: dict) -> tuple[bytes, str]:
    """The bytes of an exported file and the name to save it under.

    The export runs the same placement the page does, so what downloads is
    what was on screen rather than the undecorated chords underneath it.
    """
    key = Key.parse(params.get("key") or "C major")
    profile = Profile.load(params.get("profile") or "strict")
    progression = params.get("progression") or ""
    specs = parse_progression(progression, key)
    index = max(0, int(params.get("alt") or 0))
    soprano_text = (params.get("soprano") or "").strip()
    melody = parse_soprano(soprano_text) if soprano_text else None

    results = solve(specs, key, profile, k=index + 1, soprano=melody)
    result = results[min(index, len(results) - 1)]
    used = result.specs or specs
    tempo = float(params.get("tempo") or 84)

    # A prelude replaces the chords rather than decorating them, so it takes
    # the whole export: the figure runs off the block voicings, and the
    # embellishments chosen for the block view have nothing to attach to.
    form = PRELUDE_FORMS.get((params.get("form") or "").strip())
    if form is not None:
        data = midi_encode(prelude_spans(figurate(result.voicings, used, form)),
                           tempo_bpm=tempo, meter=form.meter)
    else:
        events, _ = place_figures(result.voicings, used, key, profile,
                                  parse_figures(params.get("figures") or ""))
        data = midi_bytes(events, tempo_bpm=tempo, meter=DEFAULT_METER)

    name = f"{key} {progression}" + (f" {form.id}" if form else "")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "harmony"
    return data, stem


def realize_payload(key_text: str, progression: str, profile_name: str,
                    alternates: int, soprano_text: str = "",
                    figures=None, position: str = "any") -> dict:
    key = Key.parse(key_text)
    profile = Profile.load(profile_name)
    # Asked for per request rather than baked into the profile, because it is
    # a choice about this phrase and not a rule about music.
    if position in ("open", "closed"):
        profile.params["position"] = position
    specs = parse_progression(progression, key)
    melody = parse_soprano(soprano_text) if soprano_text.strip() else None
    width = max(1, min(alternates, 5))
    results = solve(specs, key, profile, k=width, soprano=melody)
    chosen = [str(slot) for slot in (figures or [])]

    out = []
    for result in results:
        used = result.specs or specs
        graded = check(result.voicings, used, key, profile)
        # judged against what is already chosen, so an offer the page
        # draws is an offer that will take
        offers = opportunities(result.voicings, used, key, profile,
                               chosen=chosen)
        events, refused = place_figures(result.voicings, used, key, profile, chosen)
        out.append({
            "cost": round(result.cost, 3),
            "numerals": [sp.numeral for sp in used],
            # so the page can bracket the runs when a phrase could not be
            # written one way throughout
            "positions": [position_of(v) for v in result.voicings],
            # what a numeral *does* and what the chord *is*: two readings of
            # the same sonority, and a student wants both
            "symbols": [sp.symbol for sp in used],
            "substitutions": [
                {"chord": i, "written": w, "used": u}
                for i, w, u in result.substitutions(specs)
            ],
            "violations": [
                {"rule": v.rule_id, "voices": v.voices,
                 "chord": v.chord_index, "message": v.message}
                for v in errors_only(graded)
            ],
            "exceptions": [
                {"rule": v.rule_id, "voices": v.voices, "chord": v.chord_index,
                 "message": v.message, "reason": v.reason}
                for v in explained_breaks(graded)
            ],
            "chords": [
                {name: _note(v[name], key) for name in VOICE_NAMES}
                for v in result.voicings
            ],
            "opportunities": [
                {"chord": o.chord, "voice": o.voice, "kind": o.kind,
                 "slot": o.slot,
                 "note": _note(o.pitch, key) if o.pitch else None,
                 "refusedBy": o.refused_by}
                for o in offers
            ],
            "events": [
                {"beats": e.beats, "chord": e.chord,
                 "decorating": list(e.decorating), "tied": list(e.tied),
                 "voices": {name: _note(e.voicing[name], key)
                            for name in VOICE_NAMES}}
                for e in events
            ],
            "refused": [
                {"chord": o.chord, "voice": o.voice, "kind": o.kind,
                 "slot": o.slot, "refusedBy": o.refused_by}
                for o in refused
            ],
            # Every form, on every result, computed up front. Figurating a
            # solved realization is arithmetic over a few hundred notes,
            # where re-solving to answer a button press is the expensive
            # thing. Sending them all is what makes the picker instant.
            #
            # A note is four numbers, not an object: which chord, which rung,
            # when, how long. What pitch that is comes from the ladder, which
            # every form shares because every form climbs the same one. Spelt
            # out per note per form the payload ran past a megabyte on a long
            # progression with alternates; this way it is a few tens of KB,
            # and nothing about the figure moved into the page to get there.
            "prelude": {
                "ladders": [
                    [_note(p, key) for p in ladder_for(v, sp, PRELUDE_RUNGS)]
                    for v, sp in zip(result.voicings, used)
                ],
                "forms": {
                    form.id: {
                        "meter": f"{form.meter[0]}/{form.meter[1]}",
                        "beatsPerMeasure": form.beats_per_measure,
                        "unit": form.unit,
                        "notes": [[n.chord, n.rung, n.start, n.beats]
                                  for n in figurate(result.voicings, used, form)],
                    }
                    for form in PRELUDE_FORM_LIST
                },
            },
        })

    signature = key.signature()
    sharps = sum(1 for alt in signature.values() if alt > 0)
    flats = sum(1 for alt in signature.values() if alt < 0)

    return {
        "ok": True,
        "key": str(key),
        "signature": {
            "kind": "sharp" if sharps else ("flat" if flats else None),
            "count": sharps or flats,
        },
        "meter": f"{DEFAULT_METER[0]}/{DEFAULT_METER[1]}",
        "preludeForms": [{"id": f.id, "label": f.label,
                          "meter": f"{f.meter[0]}/{f.meter[1]}"}
                         for f in PRELUDE_FORM_LIST],
        "profile": profile.name,
        "numerals": [s.numeral for s in specs],
        "sopranoFixed": bool(melody),
        "spellings": [[str(pc) for pc in s.pitch_classes] for s in specs],
        "results": out,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = STATIC / "index.html"
            if not page.exists():
                self._send(500, b"index.html is missing", "text/plain")
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path.startswith("/api/midi"):
            self._midi(urlparse(self.path).query)
            return
        if self.path == "/api/profiles":
            names = sorted(p.stem for p in PROFILE_DIR.glob("*.json"))
            self._json(200, {"ok": True, "profiles": names, "build": _build_stamp(),
                             "version": VERSION, "released": RELEASED})
            return
        self._send(404, b"not found", "text/plain")

    def _midi(self, query: str):
        params = parse_qs(query)
        try:
            data, stem = midi_for({name: values[0]
                                   for name, values in params.items() if values})
        except (RomanNumeralError, NoRealization, ValueError, FileNotFoundError) as exc:
            self._json(200, {"ok": False, "error": str(exc)})
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/midi")
        self.send_header("Content-Disposition", f'attachment; filename="{stem}.mid"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path not in ("/api/realize", "/api/candidates", "/api/transpose"):
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "the request body was not JSON"})
            return

        if self.path in ("/api/candidates", "/api/transpose"):
            work = (candidates_payload if self.path.endswith("candidates")
                    else transpose_payload)
            try:
                self._json(200, work(request))
            except (RomanNumeralError, ValueError, FileNotFoundError) as exc:
                self._json(200, {"ok": False, "error": str(exc)})
            except Exception as exc:                  # pragma: no cover
                # The same fallback /api/realize has. Without it these two
                # answered a bad request by raising out of the handler:
                # a logged traceback, a broken connection and no reply at
                # all, where the third endpoint returns a message. A
                # soprano that is null rather than a string was enough.
                self._json(500, {"ok": False, "error": f"unexpected: {exc}"})
            return

        try:
            payload = realize_payload(
                key_text=request.get("key", "C major"),
                progression=request.get("progression", ""),
                profile_name=request.get("profile", "strict"),
                alternates=int(request.get("alternates", 1)),
                soprano_text=request.get("soprano", "") or "",
                figures=request.get("figures") or [],
                position=request.get("position", "any"),
            )
        except (RomanNumeralError, NoRealization, ValueError, FileNotFoundError) as exc:
            # These carry the explanation the engine worked out; pass it through
            # verbatim rather than flattening it to "invalid".
            self._json(200, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:                      # pragma: no cover
            self._json(500, {"ok": False, "error": f"unexpected: {exc}"})
            return

        self._json(200, payload)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"  harmony on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")


if __name__ == "__main__":
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
