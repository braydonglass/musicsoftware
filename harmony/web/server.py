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
from ..core.key import Key
from ..core.melody import candidates_for, parse_soprano
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


def realize_payload(key_text: str, progression: str, profile_name: str,
                    alternates: int, soprano_text: str = "") -> dict:
    key = Key.parse(key_text)
    profile = Profile.load(profile_name)
    specs = parse_progression(progression, key)
    melody = parse_soprano(soprano_text) if soprano_text.strip() else None
    width = max(1, min(alternates, 5))
    results = solve(specs, key, profile, k=width, soprano=melody)

    out = []
    for result in results:
        used = result.specs or specs
        graded = check(result.voicings, used, key, profile)
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
                {name: {"name": str(v[name]), "midi": v[name].midi,
                        "letter": v[name].letter, "octave": v[name].octave,
                        "alteration": v[name].alteration,
                        # Only notes departing from the key signature get a
                        # written accidental; the signature carries the rest.
                        "accidental": key.is_altered(v[name])}
                 for name in VOICE_NAMES}
                for v in result.voicings
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

        def one(name, fallback=""):
            return (params.get(name) or [fallback])[0]

        try:
            key = Key.parse(one("key", "C major"))
            profile = Profile.load(one("profile", "kostka_payne"))
            specs = parse_progression(one("progression"), key)
            index = max(0, int(one("alt", "0")))
            melody = parse_soprano(one("soprano")) if one("soprano").strip() else None
            results = solve(specs, key, profile, k=index + 1, soprano=melody)
            data = midi_bytes(
                results[min(index, len(results) - 1)].voicings,
                tempo_bpm=float(one("tempo", "84")),
                meter=FIXED_METER,
            )
        except (RomanNumeralError, NoRealization, ValueError, FileNotFoundError) as exc:
            self._json(200, {"ok": False, "error": str(exc)})
            return

        stem = re.sub(r"[^A-Za-z0-9]+", "-",
                      f"{key} {one('progression')}").strip("-").lower() or "harmony"
        self.send_response(200)
        self.send_header("Content-Type", "audio/midi")
        self.send_header("Content-Disposition", f'attachment; filename="{stem}.mid"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _candidates(self, request) -> dict:
        key = Key.parse(request.get("key", "C major"))
        profile = Profile.load(request.get("profile", "kostka_payne"))
        melody = parse_soprano(request.get("soprano", ""))
        return {
            "ok": True,
            "notes": [
                {"note": str(note), "options": candidates_for(note, key, profile)}
                for note in melody
            ],
        }

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
                self._json(200, self._candidates(request))
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
