# musicSoftware

Writes and grades four-part (SATB) chorale realizations from a key, a meter
and a sequence of Roman numerals — and lets you decorate them.

**[Try it](https://braydonglass.github.io/musicSoftware/)** — it runs entirely
in your browser. There is no server; the engine is compiled to WebAssembly and
executes locally, so the first load fetches a runtime and everything after that
is instant.

```
$ python3 -m harmony realize --key "C major" --progression "I ii6 V I"
        1     2     3     4
  S:   E5    D5    D5    C5
  A:   G4    G4    G4    E4
  T:   C4    B3    B3    G3
  B:   C3    F3    G3    C3
        I     ii6   V     I
  no violations
```

## What is in here

| | |
|---|---|
| `harmony/` | the engine, the command line and the web page |
| `harmony/README.md` | **the design notes** — the rules, why each one is a rule, and what was got wrong |
| `docs/` | the static build that GitHub Pages serves |
| `tools/build_static.py` | what generates it |

No dependencies. The tests run on stdlib `unittest`, which is also the only
reason the whole thing fits in a browser.

```
python3 -m unittest discover -s harmony/tests -t .
```

## Running it locally

```
python3 -m harmony.web.server      # the page, on http://127.0.0.1:8765
python3 -m harmony realize --help  # the command line
```

## Rebuilding the static copy

`docs/index.html` is generated, and committed because Pages serves from the
repository rather than from a build. Regenerate it after changing the engine or
the page:

```
python3 tools/build_static.py
```

There is one page, not two. It reaches the engine through a small `backend`
object: over HTTP when the Python server is behind it, and through the
in-browser runtime when it is not. The page never learns which.

## Also here

Three standalone explorers, each a single self-contained HTML file with no
build step and nothing to install: `intervals_1.html`, `pitch-explorer_1.html`
and `staff-explorer_1.html`.
