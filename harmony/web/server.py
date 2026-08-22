"""A thin HTTP layer over the engine.

Stdlib only, to keep the package dependency-free. Swapping in Flask would
touch this file and nothing else.

No rule logic lives here. This module parses a request, calls the same
functions the CLI calls, and serialises what comes back. Meter is fixed at
4/4 and never shown, because the engine stores it and the rules never see it.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..core.checker import check, errors_only, explained_breaks
from ..core.embellish import apply as place_passing
from ..core.embellish import opportunities
from ..core.key import Key
from ..core.melody import HOLE, candidates_for, parse_soprano
from ..core.midi import to_bytes as midi_bytes
from ..core.roman import RomanNumeralError, parse_progression
from ..core.rules.registry import PROFILE_DIR, Profile
from ..core.solver import NoRealization, realize, solve
from ..core.voice import VOICE_NAMES

STATIC = Path(__file__).resolve().parent / "static"
CORE = Path(__file__).resolve().parents[1] / "core"


def _build_stamp() -> str:
    """Newest mtime across the engine, so a stale server shows its age."""
    import datetime
    newest = max(p.stat().st_mtime for p in CORE.rglob("*.py"))
    return datetime.datetime.fromtimestamp(newest).strftime("%H:%M:%S")
FIXED_METER = (4, 4)


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
    """
    key = Key.parse(request.get("key", "C major"))
    profile = Profile.load(request.get("profile", "kostka_payne"))
    melody = parse_soprano(request.get("soprano", ""))
    return {
        "ok": True,
        "notes": [
            {"note": str(note) if note is not None else HOLE,
             "free": note is None,
             "options": candidates_for(note, key, profile) if note is not None else []}
            for note in melody
        ],
    }


def parse_passing(text: str) -> list[tuple[int, str]]:
    """Read the page's shorthand for chosen passing tones: "0:soprano,2:tenor".

    Anything unreadable is dropped rather than raised on. These arrive in a
    URL, and a stale or hand-edited one should still produce music.
    """
    out = []
    for token in text.split(","):
        chord, _, voice = token.strip().partition(":")
        if voice not in VOICE_NAMES:
            continue
        try:
            out.append((int(chord), voice))
        except ValueError:
            continue
    return out


def midi_for(params: dict) -> tuple[bytes, str]:
    """The bytes of an exported file and the name to save it under.

    The export runs the same placement the page does, so what downloads is
    what was on screen rather than the undecorated chords underneath it.
    """
    key = Key.parse(params.get("key") or "C major")
    profile = Profile.load(params.get("profile") or "kostka_payne")
    progression = params.get("progression") or ""
    specs = parse_progression(progression, key)
    index = max(0, int(params.get("alt") or 0))
    soprano_text = (params.get("soprano") or "").strip()
    melody = parse_soprano(soprano_text) if soprano_text else None

    results = solve(specs, key, profile, k=index + 1, soprano=melody)
    result = results[min(index, len(results) - 1)]
    events, _ = place_passing(result.voicings, result.specs or specs, key, profile,
                              parse_passing(params.get("passing") or ""))

    data = midi_bytes(events, tempo_bpm=float(params.get("tempo") or 84),
                      meter=FIXED_METER)
    stem = re.sub(r"[^A-Za-z0-9]+", "-",
                  f"{key} {progression}").strip("-").lower() or "harmony"
    return data, stem


def realize_payload(key_text: str, progression: str, profile_name: str,
                    alternates: int, soprano_text: str = "",
                    passing=None) -> dict:
    key = Key.parse(key_text)
    profile = Profile.load(profile_name)
    specs = parse_progression(progression, key)
    melody = parse_soprano(soprano_text) if soprano_text.strip() else None
    width = max(1, min(alternates, 5))
    results = solve(specs, key, profile, k=width, soprano=melody)
    chosen = [(int(chord), str(voice)) for chord, voice in (passing or [])]

    out = []
    for result in results:
        used = result.specs or specs
        graded = check(result.voicings, used, key, profile)
        offers = opportunities(result.voicings, used, key, profile)
        events, refused = place_passing(result.voicings, used, key, profile, chosen)
        out.append({
            "cost": round(result.cost, 3),
            "numerals": [sp.numeral for sp in used],
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
                {"chord": o.chord, "voice": o.voice,
                 "note": _note(o.pitch, key) if o.pitch else None,
                 "refusedBy": o.refused_by}
                for o in offers
            ],
            "events": [
                {"beats": e.beats, "chord": e.chord,
                 "passing": list(e.passing),
                 "voices": {name: _note(e.voicing[name], key)
                            for name in VOICE_NAMES}}
                for e in events
            ],
            "refused": [
                {"chord": o.chord, "voice": o.voice, "refusedBy": o.refused_by}
                for o in refused
            ],
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
        "meter": f"{FIXED_METER[0]}/{FIXED_METER[1]}",
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
            self._json(200, {"ok": True, "profiles": names, "build": _build_stamp()})
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
        if self.path not in ("/api/realize", "/api/candidates"):
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "the request body was not JSON"})
            return

        if self.path == "/api/candidates":
            try:
                self._json(200, candidates_payload(request))
            except (RomanNumeralError, ValueError, FileNotFoundError) as exc:
                self._json(200, {"ok": False, "error": str(exc)})
            return

        try:
            payload = realize_payload(
                key_text=request.get("key", "C major"),
                progression=request.get("progression", ""),
                profile_name=request.get("profile", "kostka_payne"),
                alternates=int(request.get("alternates", 1)),
                soprano_text=request.get("soprano", "") or "",
                passing=request.get("passing") or [],
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
