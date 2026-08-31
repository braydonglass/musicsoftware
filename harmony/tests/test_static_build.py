"""docs/index.html must be what the sources build.

It is a committed build artifact, which means it can be committed stale -
and it was: a page whose static source had no accidental-size slider in it
shipped with the slider still there, because the artifact next to it was
from an earlier build. Nothing caught that, because nothing was looking.

Reading the artifact is not the point. Rebuilding it and comparing is: if
the two differ, the thing being served is not the thing in the repository,
and no amount of care at commit time reliably prevents that.
"""

import pathlib
import unittest

from tools.build_static import OUT, build


class TheStaticBuildIsCurrent(unittest.TestCase):
    def test_docs_matches_a_fresh_build(self):
        before = OUT.read_text() if OUT.exists() else ""
        build()
        after = OUT.read_text()
        if before != after:
            OUT.write_text(after)          # leave the tree correct either way
        self.assertEqual(
            before, after,
            "docs/index.html was out of date and has been rebuilt - commit it. "
            "It is served to everyone who opens the site, so a stale one means "
            "the page people see is not the page in the repository.")

    def test_the_artifact_carries_the_page_it_was_built_from(self):
        """A spot check that does not depend on the comparison above."""
        page = pathlib.Path("harmony/web/static/index.html").read_text()
        built = OUT.read_text()
        marker = 'var ACC_SCALE'
        self.assertIn(marker, page)
        line = [l for l in page.splitlines() if marker in l][0].strip()
        self.assertIn(line, built,
                      f"the built page does not carry {line!r} from the source")


if __name__ == "__main__":
    unittest.main()
