"""Command line interface.

    harmony realize --key "C major" --meter 4/4 --progression "I IV V I"
    harmony check   --key "C major" --progression "I IV V I" \
                    --soprano "..." --alto "..." --tenor "..." --bass "..."
    harmony rules   --profile strict

Meter is parsed and carried, and goes no further. It exists for notation
later and for the cadential six-four's strong-beat test. If meter ever
reaches a rule check, something has gone wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap

from .core.checker import check as check_realization
from .core.melody import candidates_for, parse_soprano
from .core.midi import write as write_midi
from .core.checker import errors_only, explained_breaks, voicings_from_lines
from .core.key import Key
from .core.roman import RomanNumeralError, parse_progression
from .core.rules.registry import REGISTRY, Profile
from .core.solver import NoRealization, realize, solve
from .core.voice import VOICE_NAMES

DEFAULT_PROFILE = "strict"
_METER_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")


def parse_meter(text: str) -> tuple[int, int]:
    match = _METER_RE.match(text.strip())
    if not match:
        raise ValueError(f"cannot read {text!r} as a meter; expected something like 4/4")
    return int(match.group(1)), int(match.group(2))


# ---------------------------------------------------------------- formatting

def format_grid(voicings, specs) -> str:
    width = max(6, max(len(s.numeral) for s in specs) + 2)
    lines = []
    header = "      " + "".join(f"{i + 1:^{width}}" for i in range(len(voicings)))
    lines.append(header.rstrip())
    for name in VOICE_NAMES:
        row = "".join(f"{str(v[name]):^{width}}" for v in voicings)
        lines.append(f"  {name[0].upper()}: {row}".rstrip())
    lines.append("      " + "".join(f"{s.numeral:^{width}}" for s in specs).rstrip())
    return "\n".join(lines)


def format_json(voicings, specs, key, meter, cost) -> str:
    return json.dumps({
        "key": str(key),
        "meter": f"{meter[0]}/{meter[1]}" if meter else None,
        "progression": [s.numeral for s in specs],
        "cost": cost,
        "voices": {
            name: [str(v[name]) for v in voicings] for name in VOICE_NAMES
        },
        "chords": [
            {"numeral": s.numeral,
             "pitch_classes": [str(pc) for pc in s.pitch_classes],
             "bass": str(s.bass_pc)}
            for s in specs
        ],
    }, indent=2)


def report_violations(violations) -> str:
    if not violations:
        return "  no violations"
    lines = []
    for v in violations:
        where = ", ".join(v.voices) if v.voices else "-"
        rule = REGISTRY.get(v.rule_id)
        span = (f"chords {v.chord_index + 1}-{v.chord_index + 2}"
                if rule and rule.scope == "transition"
                else f"chord {v.chord_index + 1}")
        label = "violation" if v.severity == "error" else v.severity
        lines.append(f"  {label:10s} {v.rule_id:24s} {where:20s} {span}")
        lines.append(f"             {v.message}")
        if v.reason:
            for i, line in enumerate(textwrap.wrap(v.reason, 62)):
                lines.append(("             why: " if i == 0 else "                  ") + line)
        elif rule:
            lines.append(f"             {rule.explanation}")
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def cmd_realize(args) -> int:
    key = Key.parse(args.key)
    meter = parse_meter(args.meter) if args.meter else None
    profile = Profile.load(args.profile)
    specs = parse_progression(args.progression, key)

    melody = parse_soprano(args.soprano) if getattr(args, "soprano", None) else None

    # What was typed is a decision, so it gets the first attempt untouched.
    # solve() may still choose other inversions - either because nothing at
    # all connects as written, or because something does but it carries an
    # unwaived fault, and a cleaner answer was preferred. Those are different
    # things to tell the user, so the plain as-written search is repeated
    # here just to tell them apart.
    results = solve(specs, key, profile, k=args.alternates, soprano=melody,
                    reinvert=not args.no_reinvert)
    swaps = results[0].substitutions(specs)
    if swaps:
        try:
            realize(specs, key, profile, soprano=melody)
            reason = "as written it broke a rule; re-voiced "
        except NoRealization:
            reason = "as written it has no answer; re-voiced "
        print("  " + reason
              + ", ".join(f"{w} as {u} (chord {i})" for i, w, u in swaps))

    for index, result in enumerate(results):
        if args.format == "json":
            print(format_json(result.voicings, specs, key, meter, result.cost))
            continue
        if index:
            print(f"\n  alternate {index + 1}   cost {result.cost:.2f}")
        print(format_grid(result.voicings, result.specs or specs))
        residual = check_realization(result.voicings, result.specs or specs, key, profile)
        print(report_violations(errors_only(residual)))
        waived = explained_breaks(residual)
        if waived:
            print(f"  {len(waived)} rule{'s' if len(waived) > 1 else ''} broken on purpose:")
            for v in waived:
                where = ", ".join(v.voices) if v.voices else "-"
                print(f"    {v.rule_id}  [{where}]  chord {v.chord_index + 1}")
                print(f"      {v.message}")
                for i, line in enumerate(textwrap.wrap(v.reason, 66)):
                    print(("      why: " if i == 0 else "           ") + line)

    if args.format == "midi":
        target = args.out or "realization.mid"
        write_midi(target, results[0].voicings,
                   tempo_bpm=args.tempo, meter=meter or (4, 4))
        print(f"  wrote {target}  ({args.tempo:g} bpm)")
    return 0


def cmd_check(args) -> int:
    key = Key.parse(args.key)
    profile = Profile.load(args.profile)
    specs = parse_progression(args.progression, key)
    voicings = voicings_from_lines(args.soprano, args.alto, args.tenor, args.bass)

    if len(voicings) != len(specs):
        print(f"  {len(voicings)} chords of voices against {len(specs)} numerals",
              file=sys.stderr)
        return 2

    print(format_grid(voicings, specs))
    violations = check_realization(voicings, specs, key, profile)
    shown = violations if args.include_style else [
        v for v in violations if v.severity != "style"
    ]
    print(report_violations(shown))
    return 1 if errors_only(violations) else 0


def cmd_chords(args) -> int:
    """Which chords could harmonize each note of a melody."""
    key = Key.parse(args.key)
    profile = Profile.load(args.profile)
    melody = parse_soprano(args.soprano)
    for index, note in enumerate(melody):
        if note is None:
            print(f"  {index + 1}. _        the engine chooses this note")
            continue
        options = candidates_for(note, key, profile)
        print(f"  {index + 1}. {note}")
        if not options:
            print(f"       nothing in the vocabulary carries {note} in {key}")
            continue
        for option in options:
            print(f"       {option['numeral']:8s} {' '.join(option['spelling']):16s}"
                  f" bass {option['bass']:3s}  {option['function']}")
    return 0


def cmd_rules(args) -> int:
    profile = Profile.load(args.profile)
    print(f"  {profile.name}: {profile.description}")
    print()
    for scope in ("state", "transition"):
        print(f"  {scope} rules")
        for rule in profile.rules(scope):
            cost = "hard" if rule.is_hard else f"{rule.cost:g}"
            print(f"    {rule.id:28s} {rule.severity:8s} {cost:>5s}  {rule.category}")
            print(f"      {rule.explanation}")
            if rule.citation:
                print(f"      {rule.citation}")
        print()
    if profile.params:
        print("  parameters")
        for name, value in sorted(profile.params.items()):
            print(f"    {name:28s} {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harmony", description="Four-part harmony realizer and grader")
    subs = parser.add_subparsers(dest="command", required=True)

    r = subs.add_parser("realize", help="write an SATB realization")
    r.add_argument("--key", required=True)
    r.add_argument("--meter", default=None)
    r.add_argument("--progression", required=True)
    r.add_argument("--profile", default=DEFAULT_PROFILE)
    r.add_argument("--alternates", type=int, default=1)
    r.add_argument("--format", choices=("grid", "json", "midi"), default="grid")
    r.add_argument("--out", default=None, help="target file for --format midi")
    r.add_argument("--no-reinvert", action="store_true",
                   help="fail rather than choosing inversions for you")
    r.add_argument("--soprano", default=None,
                   help="fix the melody, e.g. \"E5 F5 D5 E5\"; the engine fills in ATB")
    r.add_argument("--tempo", type=float, default=84.0,
                   help="beats per minute written into the MIDI file")
    r.set_defaults(func=cmd_realize)

    c = subs.add_parser("check", help="grade a realization you supply")
    c.add_argument("--key", required=True)
    c.add_argument("--meter", default=None)
    c.add_argument("--progression", required=True)
    c.add_argument("--profile", default=DEFAULT_PROFILE)
    c.add_argument("--soprano", required=True)
    c.add_argument("--alto", required=True)
    c.add_argument("--tenor", required=True)
    c.add_argument("--bass", required=True)
    c.add_argument("--include-style", action="store_true",
                   help="also report style preferences, not just faults")
    c.set_defaults(func=cmd_check)

    h = subs.add_parser("chords", help="chords that could harmonize a melody")
    h.add_argument("--key", required=True)
    h.add_argument("--soprano", required=True)
    h.add_argument("--profile", default=DEFAULT_PROFILE)
    h.set_defaults(func=cmd_chords)

    u = subs.add_parser("rules", help="list the active rules")
    u.add_argument("--profile", default=DEFAULT_PROFILE)
    u.set_defaults(func=cmd_rules)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RomanNumeralError, NoRealization, ValueError, FileNotFoundError) as exc:
        print(f"  {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
