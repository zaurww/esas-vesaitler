"""Off-site copy (web/offsite.py): the daily archive written outside the
installation, the one backup that survives the program folder being deleted."""

import shutil
import tempfile
from datetime import date
from pathlib import Path

from tests.support import EngineTest, rates

from engine import mutate
from engine.mutate import inspect_archive
from engine.storage import DataError
from web import offsite
from web.update import PRESERVE


class Offsite(EngineTest):

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp())
        self.away = Path(tempfile.mkdtemp())
        (self.root / "clients").mkdir()
        rates.refresh(self.root)
        mutate.create_client(self.root, "", {
            "client_name": "Test MMC", "voen": "1234567890",
            "start_year": 2024, "status": "orta"})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.away, ignore_errors=True)

    def files(self):
        return sorted(p.name for p in (self.away / "test-mmc").glob("*.zip"))

    def test_off_by_default(self):
        self.assertEqual(offsite.run(self.root), [])

    def test_a_folder_inside_the_installation_is_refused(self):
        with self.assertRaises(DataError):
            offsite.set_folder(self.root, str(self.root / "copies"))

    def test_relative_path_is_refused(self):
        with self.assertRaises(DataError):
            offsite.set_folder(self.root, "copies")

    def test_one_archive_per_day_and_it_imports(self):
        offsite.set_folder(self.root, str(self.away))
        self.assertEqual(offsite.run(self.root, date(2026, 11, 13)), ["test-mmc"])
        self.assertEqual(offsite.run(self.root, date(2026, 11, 13)), [])
        self.assertEqual(self.files(), ["test-mmc-20261113.evbaza.zip"])
        blob = (self.away / "test-mmc" / self.files()[0]).read_bytes()
        info = inspect_archive(self.root, blob)
        self.assertEqual(info["manifest"]["slug"], "test-mmc")
        self.assertEqual(offsite.status(self.root)["clients"]["test-mmc"], "2026-11-13")

    def test_keeps_the_newest_and_leaves_foreign_files(self):
        offsite.set_folder(self.root, str(self.away))
        (self.away / "test-mmc").mkdir()
        (self.away / "test-mmc" / "mine.txt").write_text("x")
        for day in range(1, offsite.KEEP + 6):
            offsite.run(self.root, date(2026, 1, 1).fromordinal(
                date(2026, 1, 1).toordinal() + day))
        names = self.files()
        self.assertEqual(len(names), offsite.KEEP)
        self.assertTrue(names[-1].endswith(".evbaza.zip"))
        self.assertTrue((self.away / "test-mmc" / "mine.txt").exists())

    def test_missing_target_is_a_loud_error(self):
        offsite.set_folder(self.root, str(self.away))
        shutil.rmtree(self.away)
        with self.assertRaises(DataError):
            offsite.run(self.root)

    def test_setting_survives_updates(self):
        self.assertIn(offsite.SETTINGS, PRESERVE)
