"""compute_year's full output for demo-avto, diffed against tests/golden/
(see tests/golden.py for what is frozen and why, and CLAUDE.md §5.6).

A failure here means one of two things:

* an accidental regression -- fix the engine, not the snapshot;
* a deliberate change (a law update, a bug fix) -- regenerate with
  `python ev.py golden --update` and read the diff before committing. The
  diff IS the list of what moved and belongs in the release notes for it.

Either way, the fix is never to hand-edit tests/golden/demo-avto.json: it is
machine-generated output, not a fixture anyone should be typing numbers into.
"""

from __future__ import annotations

import json
import unittest

from tests.golden import DEMO_SLUG, client_snapshot, golden_path
from tests.support import EngineTest, ROOT, rates

DEMO = ROOT / "clients" / DEMO_SLUG


@unittest.skipUnless(DEMO.is_dir(), "demo-avto yoxdur")
class DemoAvtoGolden(EngineTest):

    def setUp(self):
        super().setUp()
        rates.refresh(ROOT)   # the installation's own norms, not the shipped defaults

    def test_every_figure_matches_the_committed_snapshot(self):
        path = golden_path(DEMO_SLUG)
        self.assertTrue(
            path.is_file(),
            f"{path} yoxdur -- əvvəlcə `python ev.py golden --update` işə salın")
        saved = json.loads(path.read_text(encoding="utf-8"))
        current = client_snapshot(ROOT, DEMO_SLUG)
        self.assertEqual(
            current, saved,
            "compute_year-in nəticəsi golden snapshot-dan fərqlənir -- əgər bu "
            "qəsdən edilmiş dəyişiklikdirsə (qanun yeniləməsi, xəta düzəlişi), "
            "`python ev.py golden --update` işə salıb diffi commitdən əvvəl oxuyun")


if __name__ == "__main__":
    unittest.main()
