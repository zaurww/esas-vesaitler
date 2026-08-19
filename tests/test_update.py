"""Self-update from a public GitHub release (§9, no compiled .exe).

Two things kept strictly apart, matching web/update.py's own split:

* check_latest() must never raise, no matter what `fetch` does -- a worker
  offline must see the program open normally, not an error dialog;
* apply_update() must touch exactly the files an update SHOULD touch and
  none of the ones it must not (clients/, backups/, the norm files) --
  and must leave a way back (a backup of what it overwrote).

No real network call anywhere here: `fetch` is always a stand-in.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from engine.rates import ENGINE_VERSION, version_tuple
from web.update import PRESERVE, apply_update, check_latest


class VersionTuple(unittest.TestCase):

    def test_a_higher_minor_compares_greater(self):
        self.assertGreater(version_tuple("0.10.0"), version_tuple("0.9.0"))

    def test_a_leading_v_is_stripped(self):
        self.assertEqual(version_tuple("v0.10.0"), version_tuple("0.10.0"))

    def test_equal_versions_compare_equal(self):
        self.assertEqual(version_tuple("0.9.0"), version_tuple("0.9.0"))


class CheckLatest(unittest.TestCase):

    def test_a_newer_tag_is_reported_available(self):
        fetch = lambda url: {"tag_name": "v0.10.0",
                             "zipball_url": "https://example/zip",
                             "html_url": "https://example/releases/tag/v0.10.0"}
        r = check_latest(fetch)
        self.assertTrue(r["available"])
        self.assertEqual(r["latest"], "0.10.0")
        self.assertEqual(r["current"], ENGINE_VERSION)
        self.assertEqual(r["zip_url"], "https://example/zip")

    def test_the_current_tag_is_not_available(self):
        fetch = lambda url: {"tag_name": f"v{ENGINE_VERSION}",
                             "zipball_url": "https://example/zip"}
        self.assertFalse(check_latest(fetch)["available"])

    def test_a_network_failure_degrades_to_unavailable_not_an_exception(self):
        def boom(url):
            raise OSError("no network")
        r = check_latest(boom)
        self.assertFalse(r["available"])
        self.assertIsNone(r["latest"])
        self.assertEqual(r["current"], ENGINE_VERSION)

    def test_a_malformed_response_also_degrades_quietly(self):
        r = check_latest(lambda url: {"unexpected": "shape"})
        self.assertFalse(r["available"])


def _github_zip(top: str, files: dict[str, str]) -> bytes:
    """A minimal stand-in for what GitHub's zipball_url actually returns:
    one top-level folder wrapping every entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{top}/", "")
        for name, content in files.items():
            z.writestr(f"{top}/{name}", content)
    return buf.getvalue()


class ApplyUpdate(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "ev.py").write_text("OLD EV")
        (self.root / "engine").mkdir()
        (self.root / "engine" / "rates.py").write_text("OLD RATES CODE")
        (self.root / "clients" / "demo-avto").mkdir(parents=True)
        (self.root / "clients" / "demo-avto" / "config.toml").write_text("REAL CLIENT")
        (self.root / "rates.tsv").write_text("OWNER ROW\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_app_files_are_replaced(self):
        blob = _github_zip("zaurww-esas-vesaitler-abc123", {
            "ev.py": "NEW EV",
            "engine/rates.py": "NEW RATES CODE",
        })
        apply_update(self.root, blob, from_version="0.9.0", to_version="0.10.0")
        self.assertEqual((self.root / "ev.py").read_text(), "NEW EV")
        self.assertEqual((self.root / "engine" / "rates.py").read_text(),
                         "NEW RATES CODE")

    def test_clients_are_never_touched_even_if_the_archive_carries_some(self):
        """A GitHub zipball of this repo DOES contain clients/demo-avto/
        (committed on purpose, CLAUDE.md §3) -- it must still never reach a
        worker's real clients/."""
        blob = _github_zip("zaurww-esas-vesaitler-abc123", {
            "ev.py": "NEW EV",
            "clients/demo-avto/config.toml": "SOMEONE ELSE'S DEMO",
        })
        apply_update(self.root, blob)
        self.assertEqual(
            (self.root / "clients" / "demo-avto" / "config.toml").read_text(),
            "REAL CLIENT")

    def test_owner_rate_overrides_are_never_touched(self):
        blob = _github_zip("zaurww-esas-vesaitler-abc123", {
            "ev.py": "NEW EV",
            "rates.tsv": "effective_year\tcategory\n2001\tma\n",
        })
        apply_update(self.root, blob)
        self.assertEqual((self.root / "rates.tsv").read_text(), "OWNER ROW\n")

    def test_the_old_files_are_backed_up_before_being_overwritten(self):
        blob = _github_zip("zaurww-esas-vesaitler-abc123", {"ev.py": "NEW EV"})
        apply_update(self.root, blob, from_version="0.9.0", to_version="0.10.0")
        app_backups = self.root / "backups" / "_app"
        snapshots = list(app_backups.iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertIn("0.9.0", snapshots[0].name)
        self.assertIn("0.10.0", snapshots[0].name)
        self.assertEqual((snapshots[0] / "ev.py").read_text(), "OLD EV")

    def test_an_empty_archive_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        with self.assertRaises(ValueError):
            apply_update(self.root, buf.getvalue())

    def test_an_archive_with_only_preserved_paths_is_refused(self):
        """Nothing to apply is not silently "success" -- §2.1."""
        blob = _github_zip("zaurww-esas-vesaitler-abc123", {
            "rates.tsv": "should be ignored",
        })
        with self.assertRaises(ValueError):
            apply_update(self.root, blob)

    def test_preserve_covers_every_norm_file_named_in_rates_norm_files(self):
        """rates.NORM_FILES has drifted out of sync with a hardcoded list
        before (CLAUDE.md §5.1 -- the archive code once still listed two
        files after parameters.tsv appeared). PRESERVE is a second such
        list; this pins it to the one already named once, so a norm file
        added later cannot be silently overwritten by an update without
        this test failing first."""
        from engine.rates import NORM_FILES
        self.assertTrue(set(NORM_FILES) <= PRESERVE)


if __name__ == "__main__":
    unittest.main()
