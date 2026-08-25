"""Build the static, serverless copy of the page.

The engine is stdlib Python with no dependencies, which is the one thing
that makes this possible: Pyodide can run it unchanged in the browser, so
the whole app becomes a page and needs no server at all.

There is still only one page. This reads the served one, puts a bootstrap
in front of it that fills in window.HARMONY_BACKEND with a shim calling the
same three functions inside Pyodide, and writes the result to docs/ where
GitHub Pages can find it. The page itself never learns which it is talking
to - see the backend object at the top of its script.

    python3 tools/build_static.py

Regenerate it whenever the engine or the page changes; docs/index.html is a
build artifact that happens to be committed, because Pages serves from the
repository rather than from a build.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "harmony" / "web" / "static" / "index.html"
OUT = ROOT / "docs" / "index.html"
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"


def sources() -> dict[str, str]:
    """Every file the engine needs, keyed by its path in the package."""
    out = {}
    for path in sorted(ROOT.glob("harmony/**/*.py")):
        if "tests" in path.parts:
            continue                      # the browser has no use for them
        out[str(path.relative_to(ROOT))] = path.read_text()
    for path in sorted(ROOT.glob("harmony/profiles/*.json")):
        out[str(path.relative_to(ROOT))] = path.read_text()
    return out


BOOTSTRAP = """
<script src="%(pyodide)spyodide.js"></script>
<script>
/* The engine, as files, waiting to be written into Pyodide's filesystem. */
window.HARMONY_SOURCES = %(sources)s;

(function () {
  "use strict";

  var banner = null;
  function say(text) {
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "booting";
      document.addEventListener("DOMContentLoaded", function () {
        document.body.appendChild(banner);
      });
    }
    banner.textContent = text;
  }
  say("starting the engine\\u2026");

  var ready = (async function () {
    var py = await loadPyodide({ indexURL: "%(pyodide)s" });
    /* An explicit root. Relative paths are resolved against a working
       directory that need not exist in the virtual filesystem, which fails
       with a bare ENOENT and no clue as to which file it meant. */
    var files = window.HARMONY_SOURCES;
    py.FS.mkdirTree("/app");
    Object.keys(files).forEach(function (path) {
      var full = "/app/" + path;
      py.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
      py.FS.writeFile(full, files[path]);
    });
    py.runPython([
      "import sys, json, base64",
      "sys.path.insert(0, '/app')",
      "from harmony.web.server import realize_payload, candidates_payload, midi_for",
      "from harmony.core.rules.registry import PROFILE_DIR",
      "",
      "def _realize(raw):",
      "    r = json.loads(raw)",
      "    try:",
      "        return json.dumps(realize_payload(",
      "            key_text=r.get('key', 'C major'),",
      "            progression=r.get('progression', ''),",
      "            profile_name=r.get('profile', 'strict'),",
      "            alternates=int(r.get('alternates', 1)),",
      "            soprano_text=r.get('soprano', '') or '',",
      "            figures=r.get('figures') or []))",
      "    except Exception as exc:",
      "        return json.dumps({'ok': False, 'error': str(exc)})",
      "",
      "def _candidates(raw):",
      "    try:",
      "        return json.dumps(candidates_payload(json.loads(raw)))",
      "    except Exception as exc:",
      "        return json.dumps({'ok': False, 'error': str(exc)})",
      "",
      "def _profiles():",
      "    names = sorted(p.stem for p in PROFILE_DIR.glob('*.json'))",
      "    return json.dumps({'ok': True, 'profiles': names, 'build': 'in your browser'})",
      "",
      "def _midi(raw):",
      "    data, stem = midi_for(json.loads(raw))",
      "    return json.dumps({'b64': base64.b64encode(data).decode(), 'stem': stem})",
      ""].join("\\n"));
    say("");
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    return py;
  })().catch(function (err) {
    window.__bootError = err;
    var detail = (err && (err.message || err.toString())) || String(err);
    say("the engine could not start: " + detail);
    throw err;
  });

  function call(fn, request) {
    return ready.then(function (py) {
      py.globals.set("_raw", JSON.stringify(request || {}));
      var answer = py.runPython(fn + "(_raw)");
      return JSON.parse(answer);
    });
  }

  var lastBlob = null;

  window.HARMONY_BACKEND = {
    realize: function (request) { return call("_realize", request); },
    candidates: function (request) { return call("_candidates", request); },
    profiles: function () {
      return ready.then(function (py) {
        return JSON.parse(py.runPython("_profiles()"));
      });
    },
    /* No server to fetch a file from, so the file is made here and handed
       over as a blob. The anchor stays a real URL, which is what lets it be
       opened or copied rather than depending on a scripted download. */
    midiUrl: function (params) {
      return ready.then(function (py) {
        py.globals.set("_raw", JSON.stringify(params));
        var got = JSON.parse(py.runPython("_midi(_raw)"));
        var bytes = Uint8Array.from(atob(got.b64), function (c) {
          return c.charCodeAt(0);
        });
        if (lastBlob) URL.revokeObjectURL(lastBlob);
        lastBlob = URL.createObjectURL(new Blob([bytes], { type: "audio/midi" }));
        var link = document.getElementById("export");
        if (link) link.setAttribute("download", got.stem + ".mid");
        return lastBlob;
      });
    },
  };
})();
</script>
<style>
  #booting {
    position: fixed; left: 50%%; top: 18px; transform: translateX(-50%%);
    font-family: var(--mono); font-size: 12px; color: var(--amber);
    background: var(--panel-deep); border: 1px solid var(--amber-dim);
    border-radius: 3px; padding: 7px 13px; z-index: 9;
  }
  #booting:empty { display: none; }
</style>
"""


def build() -> pathlib.Path:
    page = PAGE.read_text()
    boot = BOOTSTRAP % {
        "pyodide": PYODIDE,
        "sources": json.dumps(sources(), indent=0),
    }
    # In front of the page's own script, because the page reads
    # window.HARMONY_BACKEND the moment it runs.
    marker = "<script>\n(function () {"
    if marker not in page:
        raise SystemExit("the page's script does not start where expected")
    page = page.replace(marker, boot + "\n" + marker, 1)
    page = page.replace(
        "<title>Four-Part Harmony</title>",
        "<title>Four-Part Harmony</title>\n"
        "<meta name=\"description\" content=\"Writes and grades four-part chorale "
        "realizations in the browser.\">")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page)
    return OUT


if __name__ == "__main__":
    written = build()
    size = written.stat().st_size / 1024
    print(f"  wrote {written.relative_to(ROOT)}  ({size:.0f} KB)")
