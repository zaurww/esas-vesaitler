"""The write path: §8 (atomic write, backup, changelog) and §8.1 (re-read and
recompute after every write, roll back if the store no longer computes).

Every test here works in a temporary root, so nothing touches the real
clients/ folder.
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tests.support import EngineTest, rates

from engine import mutate
from engine.calc import CalcError, compute_year
from engine.storage import DataError, load_client, read_tsv


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
        snapshots = [p for p in (self.root / "backups" / self.slug).iterdir()
                     if p.is_dir()]
        self.assertEqual(len(snapshots), 1)
        # ... and still one changelog line per object.
        rows = [r for r in mutate.rows_of(self.root, self.slug, "changelog.tsv")
                if r["field"] == "asset"]
        self.assertEqual(len(rows), 50)


class Backups(TempRoot):
    """§13.4: the folder used to grow without limit on a machine whose owner
    is not in the loop. It is bounded now -- but only where bounding it cannot
    cost somebody the single copy of what they deleted by mistake."""

    def snap(self, days_ago: float, action: str = "asset.update") -> Path:
        when = datetime.now() - timedelta(days=days_ago)
        p = (self.root / "backups" / self.slug /
             f"{when.strftime('%Y%m%d-%H%M%S-%f')}-{action}")
        p.mkdir(parents=True)
        return p

    def snaps(self) -> list[str]:
        folder = self.root / "backups" / self.slug
        return sorted(p.name for p in folder.iterdir() if p.is_dir())

    def many(self, n: int, days_ago: float) -> None:
        for i in range(n):
            self.snap(days_ago + i / 1440)

    def test_a_snapshot_is_named_after_the_action_it_preceded(self):
        """The keep-always rule has nothing else to read, and neither has the
        person hunting for the state before a particular change."""
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        self.assertTrue(self.snaps()[0].endswith("-asset.create"))

    def test_recent_snapshots_survive_however_many_there_are(self):
        self.many(mutate.BACKUP_KEEP_COUNT + 20, days_ago=1)
        self.assertEqual(mutate.prune_backups(self.root, self.slug), 0)

    def test_old_snapshots_survive_while_they_are_among_the_last_kept(self):
        self.many(mutate.BACKUP_KEEP_COUNT, days_ago=400)
        self.assertEqual(mutate.prune_backups(self.root, self.slug), 0)

    def test_old_AND_beyond_the_count_is_what_goes(self):
        self.many(mutate.BACKUP_KEEP_COUNT + 3, days_ago=400)
        self.assertEqual(mutate.prune_backups(self.root, self.slug), 3)
        self.assertEqual(len(self.snaps()), mutate.BACKUP_KEEP_COUNT)

    def test_the_snapshot_before_a_close_is_never_deleted(self):
        """§13.4: closing a year is the one act coming back from is expensive,
        so that snapshot outweighs any N and M."""
        sealed = self.snap(500, action="year.close")
        self.many(mutate.BACKUP_KEEP_COUNT + 5, days_ago=400)
        mutate.prune_backups(self.root, self.slug)
        self.assertTrue(sealed.is_dir())

    def test_a_folder_we_did_not_write_is_left_alone(self):
        """Only what this program created is this program's to delete."""
        mine = self.root / "backups" / self.slug / "əl ilə saxlanılıb"
        mine.mkdir(parents=True)
        self.many(mutate.BACKUP_KEEP_COUNT + 5, days_ago=400)
        mutate.prune_backups(self.root, self.slug)
        self.assertTrue(mine.is_dir())

    def test_the_cleanup_says_where_the_backups_went(self):
        """Nobody would otherwise be able to answer that question, and
        changelog.tsv is for the client's facts, not the program's."""
        self.many(mutate.BACKUP_KEEP_COUNT + 2, days_ago=400)
        mutate.prune_backups(self.root, self.slug)
        rows = read_tsv(self.root / "backups" / self.slug / "_cleanup.tsv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["removed"], "2")
        self.assertEqual(rows[0]["kept"], str(mutate.BACKUP_KEEP_COUNT))

    def test_a_write_never_prunes_its_own_backup(self):
        """The rollback restores from the snapshot this transaction just took;
        cleaning runs before the copy so it can never be a candidate."""
        self.many(mutate.BACKUP_KEEP_COUNT + 5, days_ago=400)
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        self.assertTrue(self.snaps()[-1].endswith("-asset.create"))
        self.assertEqual(len(self.snaps()), mutate.BACKUP_KEEP_COUNT + 1)


class OwnerNorms(TempRoot):
    """§5.1: the owner's rate rows live in the installation root and touch
    every client, so writing one recomputes all of them."""

    def test_an_owner_rate_row_reaches_the_table(self):
        """This path raised ModuleNotFoundError for as long as the suite did
        not walk it: splitting mutate.py into a package turned an intra-file
        `from .storage import` into a reference to engine.mutate.storage."""
        mutate.set_rate_row(self.root, self.slug, {
            "effective_year": 2030, "category": "ma", "max_rate": "0.15"})
        self.assertEqual(rates.statutory(2030, "ma").max_rate, Decimal("0.15"))

    def test_a_rate_that_breaks_a_client_is_rolled_back(self):
        """§8.1 for the norms: an election legal under 20% is not legal under
        5%, and the client it breaks is not necessarily the one on screen."""
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "A", "cost": "1000",
            "in_date": "2024-01-01"})
        mutate.set_election(self.root, self.slug, {
            "year": 2024, "category": "ma", "applied_rate": "0.20"})
        with self.assertRaises(CalcError):
            mutate.set_rate_row(self.root, self.slug, {
                "effective_year": 2024, "category": "ma", "max_rate": "0.05",
                "allow_past": True})
        self.assertEqual(rates.statutory(2024, "ma").max_rate, Decimal("0.20"))


class StartOver(TempRoot):
    """Clearing the card list -- "import again from scratch" (§11.2).

    Import appends and always has, which is right: "this file replaces
    everything" is a much bigger claim than "these rows are assets". So
    starting over is a separate, named act, and these tests pin down what it
    takes with it and what it must leave alone.
    """

    def setUp(self):
        super().setUp()
        mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "ma", "name": "Dəzgah",
            "in_date": "2024-04-01", "cost": "1000", "say": "3"})
        self.aid = self.client().assets[0].asset_id
        mutate.add_repair(self.root, self.slug, {
            "asset_id": self.aid, "year": 2024, "date": "2024-06-01",
            "amount": "50"})
        mutate.set_election(self.root, self.slug, {
            "year": 2024, "category": "ma", "applied_rate": "0.10"})

    def clear(self, confirm="Test MMC"):
        return mutate.clear_assets(self.root, self.slug, {"confirm": confirm})

    def test_the_cards_and_what_hangs_off_them_go(self):
        self.clear()
        d = self.client()
        self.assertEqual(d.assets, [])
        self.assertEqual(d.repairs, [])
        self.assertEqual(d.opening_balances, [])

    def test_what_the_import_never_touched_stays(self):
        """Re-typing the status and the category rate would be re-entering
        work that was never part of the sheet."""
        self.clear()
        d = self.client()
        self.assertEqual([s.status for s in d.statuses], ["orta"])
        self.assertEqual([e.category for e in d.elections], ["ma"])

    def test_the_slug_is_accepted_as_confirmation_too(self):
        self.clear(confirm="  TEST-MMC ")
        self.assertEqual(self.client().assets, [])

    def test_a_wrong_name_changes_nothing(self):
        with self.assertRaises(DataError):
            self.clear(confirm="Başqa MMC")
        self.assertEqual(len(self.client().assets), 3)

    def test_a_closed_year_refuses_it(self):
        """The sealed balances are the evidence behind a filed return (§6.2);
        wiping them would leave `verify` unable to check the years it exists
        for. Reopening first is the deliberate way through."""
        mutate.close_year(self.root, self.slug, {"year": 2024})
        with self.assertRaises(DataError):
            self.clear()
        self.assertEqual(len(self.client().assets), 3)

    def test_it_leaves_a_backup_and_a_changelog_line(self):
        self.clear()
        snaps = [p.name for p in (self.root / "backups" / self.slug).iterdir()
                 if p.name.endswith("asset.clear")]
        self.assertTrue(snaps)
        log = read_tsv(self.root / "clients" / self.slug / "changelog.tsv")
        self.assertTrue(any(r["action"] == "asset.clear" for r in log))

    def test_the_import_preview_says_how_many_are_already_there(self):
        """The warning that makes the trap visible: with blank inventory
        numbers a second import of the same sheet duplicates silently."""
        rep = mutate.import_assets(self.root, self.slug, {
            "rows": [{"name": "Yeni", "category": "ma", "in_date": "2024-05-05",
                      "cost": "500"}], "dry_run": True})
        self.assertEqual(rep["existing"], 3)


class Groups(TempRoot):
    """«Növ» -- the client's own classification beside the tax one (§13.1).

    The one invariant worth more than all the rest: it changes no figure. Set
    up here on the write path, and asserted on the numbers in
    test_pipeline.GroupsChangeNothing.
    """

    def make(self, name="Serverlər"):
        return mutate.create_group(self.root, self.slug, {"name": name})

    def asset(self, name="Server", group_id=""):
        return mutate.create_asset(self.root, self.slug, {
            "mode": "new", "category": "yt", "name": name,
            "in_date": "2024-03-01", "cost": "5000", "group_id": group_id})

    def test_a_group_survives_a_round_trip(self):
        gid = self.make()
        aid = self.asset(group_id=gid)
        d = self.client()
        self.assertEqual([g.name for g in d.groups], ["Serverlər"])
        self.assertEqual(d.group_name(gid), "Serverlər")
        card = next(a for a in d.assets if a.asset_id == aid)
        self.assertEqual(card.group_id, gid)
        self.assertEqual(d.card_meta()[aid]["group"], "Serverlər")

    def test_the_same_name_twice_is_refused(self):
        """A dictionary exists so that «Serverlər» cannot become two groups;
        matching is case- and space-insensitive for the same reason (§2.1)."""
        self.make("Serverlər")
        with self.assertRaises(DataError):
            self.make("  serverlər ")

    def test_renaming_touches_no_card(self):
        """The card stores the id, so a rename is one edit here -- the same
        reasoning that keeps inv_no out of the key position (§4)."""
        gid = self.make()
        aid = self.asset(group_id=gid)
        before = read_tsv(self.root / "clients" / self.slug / "assets.tsv")
        mutate.update_group(self.root, self.slug,
                            {"group_id": gid, "name": "Server avadanlığı"})
        after = read_tsv(self.root / "clients" / self.slug / "assets.tsv")
        self.assertEqual(before, after)
        self.assertEqual(self.client().card_meta()[aid]["group"],
                         "Server avadanlığı")

    def test_a_group_in_use_is_not_deleted(self):
        """Clearing forty cards as a side effect of one click is data loss
        wearing the clothes of tidying up."""
        gid = self.make()
        self.asset(group_id=gid)
        with self.assertRaises(DataError):
            mutate.delete_group(self.root, self.slug, {"group_id": gid})
        self.assertEqual(len(self.client().groups), 1)

    def test_an_empty_group_is_deleted(self):
        gid = self.make()
        mutate.delete_group(self.root, self.slug, {"group_id": gid})
        self.assertEqual(self.client().groups, [])

    def test_assigning_is_one_transaction_for_many_cards(self):
        """One backup and one recompute for one act of sorting (§8.1,
        §5.3-bis) -- and the changelog still gets a line per card."""
        gid = self.make()
        ids = [self.asset(f"Server {i}") for i in range(3)]
        mutate.assign_group(self.root, self.slug,
                            {"group_id": gid, "asset_ids": ids})
        d = self.client()
        self.assertEqual({a.group_id for a in d.assets}, {gid})
        log = read_tsv(self.root / "clients" / self.slug / "changelog.tsv")
        moved = [r for r in log if r["field"] == "group_id"]
        self.assertEqual(len(moved), 3)
        self.assertEqual({r["action"] for r in moved}, {"group.assign"})

    def test_assigning_an_empty_group_clears_the_field(self):
        gid = self.make()
        aid = self.asset(group_id=gid)
        mutate.assign_group(self.root, self.slug,
                            {"group_id": "", "asset_ids": [aid]})
        self.assertEqual(self.client().assets[0].group_id, "")

    def test_an_unknown_group_is_refused_at_the_door(self):
        with self.assertRaises(DataError):
            self.asset(group_id="QR-999")

    def test_a_dangling_reference_is_refused_at_read_time(self):
        """Files are plain text and people will edit them (§3), so the store
        checks on the way in as well as on the way out."""
        gid = self.make()
        self.asset(group_id=gid)
        path = self.root / "clients" / self.slug / "groups.tsv"
        path.write_text("group_id\tname\tnote\n", encoding="utf-8-sig")
        with self.assertRaises(DataError):
            self.client()

    def test_a_closed_year_does_not_block_grouping(self):
        """Closing seals the RETURN, not the card (§6.2): a group reaches no
        figure, so sorting a 2024 asset cannot change a filed 2024."""
        gid = self.make()
        aid = self.asset()
        mutate.close_year(self.root, self.slug, {"year": 2024})
        mutate.assign_group(self.root, self.slug,
                            {"group_id": gid, "asset_ids": [aid]})
        self.assertEqual(self.client().assets[0].group_id, gid)


class GroupImport(TempRoot):
    """A «Növ» column in a bulk import carries NAMES from the client's sheet."""

    def rows(self, *groups):
        return [{"name": f"Obyekt {i}", "category": "ma", "in_date": "2024-05-05",
                 "cost": "1000", "group": g} for i, g in enumerate(groups)]

    def test_names_become_one_group_each_however_they_are_typed(self):
        mutate.import_assets(self.root, self.slug, {
            "rows": self.rows("Serverlər", "serverlər", " Serverlər  ",
                              "Printerlər")})
        d = self.client()
        self.assertEqual(sorted(g.name for g in d.groups),
                         ["Printerlər", "Serverlər"])
        meta = d.card_meta()
        self.assertEqual([meta[a.asset_id]["group"] for a in d.assets],
                         ["Serverlər", "Serverlər", "Serverlər", "Printerlər"])

    def test_a_dry_run_leaves_no_group_behind(self):
        """The preview validates through the real path and rolls back, so a
        group invented for a row that never landed must not survive it."""
        rep = mutate.import_assets(self.root, self.slug, {
            "rows": self.rows("Serverlər"), "dry_run": True})
        self.assertEqual(rep["groups_created"], 1)
        self.assertEqual(self.client().groups, [])

    def test_an_existing_group_is_reused_not_duplicated(self):
        gid = mutate.create_group(self.root, self.slug, {"name": "Serverlər"})
        mutate.import_assets(self.root, self.slug, {"rows": self.rows("SERVERLƏR")})
        d = self.client()
        self.assertEqual(len(d.groups), 1)
        self.assertEqual(d.assets[0].group_id, gid)


class PathSafety(EngineTest):
    """§4: the client name reaches the filesystem, so it must not be able to
    point outside clients/."""

    def test_traversal_is_refused(self):
        for bad in ("..", "../evil", "a/b", "a\\b", ""):
            with self.assertRaises(DataError, msg=bad):
                mutate.one_segment(bad)

    def test_slugify_transliterates_to_ascii(self):
        self.assertEqual(mutate.slugify('«Şəfa Tibb» MMC'), "sefa-tibb-mmc")

    def test_a_capital_dotted_i_does_not_split_the_slug(self):
        """Python lowercases «İ» to "i" plus a combining dot, and the dot was
        not in the map -- «Sınaq İdxal MMC» came out as `sinaq-i-dxal-mmc`."""
        self.assertEqual(mutate.slugify("Sınaq İdxal MMC"), "sinaq-idxal-mmc")
        self.assertEqual(mutate.slugify("İSTEHSAL"), "istehsal")

    def test_slugify_never_returns_empty(self):
        self.assertEqual(mutate.slugify("«»"), "musteri")

    def test_cyrillic_look_alikes_do_not_survive(self):
        """A Cyrillic е produced a folder nobody could reach by its ASCII
        name; both creation paths now go through slugify (§4)."""
        self.assertNotIn("е", mutate.slugify("еtest"))


class QmaCards(TempRoot):
    """A QMA on the write path (§4, §5.3).

    It is an ordinary card, so most of the store needs no new machinery -- and
    that is exactly why the two fields the SCHEDULE depends on have to be
    guarded here as well as in the calculation: a card saved without a term is
    a card that stops the year computing for everyone else in it.
    """

    def make(self, **kw):
        p = {"mode": "new", "category": "qma-m", "name": "1C proqramı",
             "cost": "6000", "in_date": "2024-03-01", "useful_life": "5"}
        p.update(kw)
        return mutate.create_asset(self.root, self.slug, p)

    def test_a_known_term_card_round_trips(self):
        aid = self.make()
        a = next(a for a in self.client().assets if a.asset_id == aid)
        self.assertEqual(a.category, "qma-m")
        self.assertEqual(a.useful_life, 5)

    def test_and_computes_on_the_straight_line(self):
        self.make()
        r = compute_year(self.client(), 2024)
        self.assertEqual(str(r.totals["depreciation"]), "1200.00")

    def test_a_known_term_card_without_a_term_is_refused(self):
        with self.assertRaises(DataError) as e:
            self.make(useful_life="")
        self.assertIn("FİM", str(e.exception))

    def test_a_term_on_an_unknown_term_card_is_refused(self):
        """Both halves of 114.3.6 at once. Ignoring it would cost ten years
        against five, silently."""
        with self.assertRaises(DataError):
            self.make(category="qma-n", useful_life="5")

    def test_an_unknown_term_card_needs_no_term(self):
        aid = self.make(category="qma-n", useful_life="")
        self.assertIsNone(next(a for a in self.client().assets
                               if a.asset_id == aid).useful_life)

    def test_a_qma_carried_from_earlier_years_still_needs_its_date(self):
        """`carried` lets a fixed asset in without a date -- only the residual
        matters there. A straight line has to know which year is year zero."""
        with self.assertRaises(DataError):
            self.make(mode="carried", in_date="", opening_residual="3000",
                      opening_year="2024", cost="")

    def test_a_group_pool_cannot_be_a_qma(self):
        """A pool stands for a category with no cards (§6.1): no date, no
        term, and 10% of a residual is the one thing a straight line will not
        do."""
        with self.assertRaises(DataError):
            self.make(mode="pool", opening_residual="3000",
                      opening_year="2024", useful_life="")

    def test_the_term_can_be_corrected_on_the_card(self):
        aid = self.make()
        mutate.update_asset(self.root, self.slug, {
            "asset_id": aid, "inv_no": "QMA-0001", "name": "1C proqramı",
            "category": "qma-m", "in_date": "2024-03-01", "cost": "6000",
            "useful_life": "3"})
        self.assertEqual(self.client().assets[0].useful_life, 3)
        r = compute_year(self.client(), 2024)
        self.assertEqual(str(r.totals["depreciation"]), "2000.00")

    def test_a_hand_edited_file_is_caught_on_read(self):
        """§3: the files are plain text and people edit them, so the same rule
        has to hold on the way in."""
        self.make()
        f = self.root / "clients" / self.slug / "assets.tsv"
        f.write_text(f.read_text(encoding="utf-8-sig").replace("\t5\t", "\t\t"),
                     encoding="utf-8-sig")
        with self.assertRaises(DataError):
            self.client()


if __name__ == "__main__":
    unittest.main()
