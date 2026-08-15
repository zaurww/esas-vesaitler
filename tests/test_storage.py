"""The write path: §8 (atomic write, backup, changelog) and §8.1 (re-read and
recompute after every write, roll back if the store no longer computes).

Every test here works in a temporary root, so nothing touches the real
clients/ folder.
"""

import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tests.support import EngineTest, rates

from engine import mutate
from engine.calc import compute_year
from engine.storage import DataError, load_client


class TempRoot(EngineTest):

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp())
        (self.root / "clients").mkdir()
        rates.refresh(self.root)
        mutate.create_client(self.root, "", {
            "client_name": "Test MMC", "voen": "1234567890",
            "start_year": 2024, "status": "orta"})
        self.slug = "test-mmc"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def client(self):
        return load_client(self.root, self.slug)


class Roundtrip(TempRoot):

    def test_a_fresh_client_loads_immediately(self):
        """§4: the folder is valid from the first second, not built up as
        features get used."""
        d = self.client()
        self.assertEqual(d.client_name, "Test MMC")
        self.assertEqual(d.start_year, 2024)
        self.assertEqual([s.status for s in d.statuses], ["orta"])

    def test_files_are_written_with_a_bom(self):
        """§4/§11: without it Excel and Notepad mangle ə ç ş ğ ı ö ü."""
        raw = (self.root / "clients" / self.slug / "assets.tsv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))

    def test_a_quoted_company_name_survives_config_toml(self):
        """A legal name like «Şəfa Tibb» "MMC" used to produce a config the
        parser then refused -- the client could not be opened again (§4)."""
        mutate.update_client(self.root, self.slug,
                             {"client_name": '«Şəfa Tibb» "MMC"',
                              "voen": "1", "start_year": "2024"})
        self.assertEqual(self.client().client_name, '«Şəfa Tibb» "MMC"')

    def test_decimals_round_trip_exactly(self):
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "Dəzgah",
            "cost": "1234.56", "in_date": "2024-03-01"})
        self.assertEqual(self.client().assets[0].cost, Decimal("1234.56"))

    def test_the_new_optional_fields_round_trip(self):
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "Server",
            "cost": "8400", "in_date": "2024-03-01",
            "e_qaime": "EQ-2026-77421", "serial_no": "SRV-99881"})
        a = self.client().assets[0]
        self.assertEqual(a.e_qaime, "EQ-2026-77421")
        self.assertEqual(a.serial_no, "SRV-99881")


class Batches(TempRoot):
    """§4: quantity is a form field, never stored -- it becomes N cards."""

    def create(self, say):
        return mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "dg", "name": "Soyuducu",
            "cost": "400", "in_date": "2024-05-01", "say": str(say),
            "e_qaime": "EQ-1", "serial_no": "SN-1"})

    def test_n_cards_are_created(self):
        self.create(240)
        self.assertEqual(len(self.client().assets), 240)

    def test_inventory_numbers_are_a_series(self):
        self.create(5)
        self.assertEqual([a.inv_no for a in self.client().assets],
                         ["DG-0001", "DG-0002", "DG-0003",
                          "DG-0004", "DG-0005"])

    def test_a_batch_shares_the_invoice_but_not_the_serial(self):
        self.create(3)
        assets = self.client().assets
        self.assertEqual({a.e_qaime for a in assets}, {"EQ-1"})
        self.assertEqual({a.serial_no for a in assets}, {""})

    def test_a_single_card_keeps_its_serial(self):
        self.create(1)
        self.assertEqual(self.client().assets[0].serial_no, "SN-1")

    def test_each_card_is_tested_against_the_threshold_separately(self):
        """The whole reason quantity is not a column: 240 x 400 as one line
        would never fall under 114.8, while each 400 does (§4).

        400 -> 320 at the end of 2024, which is under 500, so 2025 is the year
        the decision is offered (§5.3-bis)."""
        self.create(240)
        for year in (2025, 2026):
            mutate.set_status(self.root, self.slug,
                              {"year": year, "status": "orta"})
        r = compute_year(self.client(), 2025)
        self.assertEqual(len(r.threshold_cards), 240)

    def test_an_absurd_quantity_is_refused(self):
        with self.assertRaises(DataError):
            self.create(50000)


class WriteProtection(TempRoot):

    def test_duplicate_inventory_number_is_refused(self):
        for _ in range(1):
            mutate.create_asset(self.root, self.slug, {
                "mode": "new", "category": "ma", "name": "A", "cost": "100",
                "in_date": "2024-01-01", "inv_no": "MA-0001"})
        with self.assertRaises(DataError):
            mutate.create_asset(self.root, self.slug, {
                "mode": "new", "category": "ma", "name": "B", "cost": "100",
                "in_date": "2024-01-01", "inv_no": "MA-0001"})
        self.assertEqual(len(self.client().assets), 1)

    def test_a_rate_above_the_ceiling_is_rolled_back(self):
        """§8.1: the row is valid TSV and passes field validation; only the
        recompute catches it, and the write is undone."""
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        before = (self.root / "clients" / self.slug
                  / "rate_elections.tsv").read_bytes()
        with self.assertRaises(Exception):
            mutate.set_election(self.root, self.slug,
                                {"year": 2024, "category": "ma",
                                 "applied_rate": "90"})
        after = (self.root / "clients" / self.slug
                 / "rate_elections.tsv").read_bytes()
        self.assertEqual(before, after)
        compute_year(self.client(), 2024)      # still computes

    def close_2024(self):
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        mutate.close_year(self.root, self.slug, {"year": 2024})
        self.assertIn(2024, self.client().closed_years())
        return self.client().assets[0].asset_id

    def test_an_asset_cannot_be_acquired_into_a_closed_year(self):
        """Regression: only the opening-balance year was guarded, so an asset
        dated inside a filed year went straight in -- the year stopped
        matching its own seal and nothing said so until `ev.py verify`."""
        self.close_2024()
        with self.assertRaises(DataError):
            mutate.create_asset(self.root, self.slug, {
                "mode": "new", "category": "ma", "name": "B", "cost": "1000",
                "in_date": "2024-06-01"})
        self.assertEqual(len(self.client().assets), 1)

    def test_a_later_year_is_still_open(self):
        self.close_2024()
        mutate.set_status(self.root, self.slug,
                          {"year": 2025, "status": "orta"})
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "B", "cost": "1000",
            "in_date": "2025-06-01"})
        self.assertEqual(len(self.client().assets), 2)

    def test_figures_of_an_asset_in_a_closed_year_are_frozen(self):
        aid = self.close_2024()
        with self.assertRaises(DataError):
            mutate.update_asset(self.root, self.slug, {
                "asset_id": aid, "inv_no": "MA-0001", "name": "A",
                "category": "ma", "in_date": "2024-01-01", "cost": "9999"})
        self.assertEqual(self.client().assets[0].cost, Decimal("1000"))

    def test_but_its_description_can_still_be_corrected(self):
        """A closed year seals the return, not the card: a misspelt name or a
        missing serial changes no figure."""
        aid = self.close_2024()
        mutate.update_asset(self.root, self.slug, {
            "asset_id": aid, "inv_no": "MA-0001", "name": "Dəzgah",
            "category": "ma", "in_date": "2024-01-01", "cost": "1000",
            "serial_no": "SN-7"})
        a = self.client().assets[0]
        self.assertEqual(a.name, "Dəzgah")
        self.assertEqual(a.serial_no, "SN-7")

    def test_an_asset_cannot_be_moved_out_of_a_closed_year_either(self):
        aid = self.close_2024()
        mutate.set_status(self.root, self.slug,
                          {"year": 2025, "status": "orta"})
        with self.assertRaises(DataError):
            mutate.update_asset(self.root, self.slug, {
                "asset_id": aid, "inv_no": "MA-0001", "name": "A",
                "category": "ma", "in_date": "2025-06-01", "cost": "1000"})

    def test_reopening_removes_the_seal(self):
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        mutate.close_year(self.root, self.slug, {"year": 2024})
        mutate.reopen_year(self.root, self.slug, {"year": 2024})
        self.assertNotIn(2024, self.client().closed_years())

    def test_every_write_leaves_a_changelog_line(self):
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        rows = mutate.rows_of(self.root, self.slug, "changelog.tsv")
        self.assertTrue(rows)
        self.assertTrue(all(r["timestamp"] and r["action"] for r in rows))

    def test_a_batch_is_one_backup_not_two_hundred(self):
        """§4: one act of the bookkeeper, one transaction -- otherwise §8.1
        would back the folder up 240 times for a single purchase."""
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "dg", "name": "Soyuducu",
            "cost": "400", "in_date": "2024-05-01", "say": "50"})
        snapshots = list((self.root / "backups" / self.slug).iterdir())
        self.assertEqual(len(snapshots), 1)
        # ... and still one changelog line per object.
        rows = [r for r in mutate.rows_of(self.root, self.slug, "changelog.tsv")
                if r["field"] == "asset"]
        self.assertEqual(len(rows), 50)


class PathSafety(EngineTest):
    """§4: the client name reaches the filesystem, so it must not be able to
    point outside clients/."""

    def test_traversal_is_refused(self):
        for bad in ("..", "../evil", "a/b", "a\\b", ""):
            with self.assertRaises(DataError, msg=bad):
                mutate.one_segment(bad)

    def test_slugify_transliterates_to_ascii(self):
        self.assertEqual(mutate.slugify('«Şəfa Tibb» MMC'), "sefa-tibb-mmc")

    def test_slugify_never_returns_empty(self):
        self.assertEqual(mutate.slugify("«»"), "musteri")

    def test_cyrillic_look_alikes_do_not_survive(self):
        """A Cyrillic е produced a folder nobody could reach by its ASCII
        name; both creation paths now go through slugify (§4)."""
        self.assertNotIn("е", mutate.slugify("еtest"))


if __name__ == "__main__":
    unittest.main()
