"""Files, transactions and the closed-year guard.

The four steps every write goes through live here: back the folder up, apply
the change, re-read and recompute the whole store, roll back if it no longer
computes (CLAUDE.md §8.1). Everything else in this package is an action that
runs inside `transaction`."""

from __future__ import annotations

import getpass
import shutil

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .. import rates
from ..calc import compute_year
from ..storage import (
    DataError, append_tsv, list_clients, load_client, read_tsv, write_tsv,
)

HEADERS: dict[str, list[str]] = {
    # e_qaime / serial_no were appended, never inserted: a new optional column
    # leaves format_version alone (§7), and an older engine reading this file
    # simply ignores it -- which is safe here precisely because neither figure
    # enters the calculation.
    "assets.tsv": ["asset_id", "inv_no", "name", "category", "in_date", "cost",
                   "counterparty", "useful_life", "is_legacy_pool", "note",
                   "e_qaime", "serial_no"],
    "opening_balances.tsv": ["year", "asset_id", "category", "residual", "source",
                             "engine_version", "closed_at"],
    "disposals.tsv": ["asset_id", "date", "type", "proceeds"],
    "repairs.tsv": ["year", "asset_id", "date", "amount", "note"],
    "additions.tsv": ["year", "asset_id", "date", "amount", "note"],
    "taxpayer_status.tsv": ["year", "status", "basis", "use_coefficient"],
    "rate_elections.tsv": ["year", "category", "applied_rate", "asset_id"],
    "writeoffs.tsv": ["year", "asset_id", "reason"],
    "changelog.tsv": ["timestamp", "user", "action", "asset_id", "field",
                      "old_value", "new_value"],
}


def one_segment(slug: str) -> str:
    """A client slug names ONE folder under clients/ and nothing else.

    Every action carries the slug in from the request, so without this a
    crafted value ("../..") would address a path outside the store. Only
    traversal is refused here, not slug shape: folders created before
    slugify was applied on import are odd-looking but harmless, and
    breaking access to an existing client is worse than an ugly name.
    """
    s = str(slug or "").strip()
    if not s or s in (".", "..") or "/" in s or "\\" in s or Path(s).is_absolute():
        raise DataError(f"müştəri adı yolverilməzdir: {slug!r}")
    return s


def mutate_folder(root: Path, slug: str) -> Path:
    f = root / "clients" / one_segment(slug)
    if not f.is_dir():
        raise DataError(f"müştəri tapılmadı: {slug}")
    return f


def rows_of(root: Path, slug: str, name: str) -> list[dict[str, str]]:
    header = HEADERS[name]
    out = []
    for r in read_tsv(mutate_folder(root, slug) / name):
        out.append({h: r.get(h, "") for h in header})
    return out


def save_rows(root: Path, slug: str, name: str, rows: list[dict[str, str]]) -> None:
    header = HEADERS[name]
    write_tsv(mutate_folder(root, slug) / name,
              header, [[r.get(h, "") for h in header] for r in rows])


# ----------------------------------------------------------------- backups ---

# A snapshot is deleted only when it is BOTH older than KEEP_DAYS and beyond
# the last KEEP_COUNT. The two rules protect the union of what each covers,
# and either alone throws away the case the other one holds: "last 100" loses
# last month's mistake after one busy week, "last 90 days" loses everything
# after a quiet quarter. A backup is regularly the ONLY copy of what somebody
# deleted by accident and missed a week later (§8.1), so the generous side is
# the correct side to err on -- measured at ~20 KB per snapshot on a client
# with 242 cards, keeping a hundred of them costs about 2 MB.
#
# Not figures of the law, so they live in code rather than in the parameter
# registry -- the line §5.1-bis draws. Precedent: BATCH_MAX.
BACKUP_KEEP_DAYS = 90
BACKUP_KEEP_COUNT = 100

# The snapshots no rule may delete. Closing a year is the one act after which
# coming back is expensive (§6.2), so the folder as it stood just before it
# outweighs any N and M.
BACKUP_KEEP_ALWAYS = ("year.close",)

BACKUP_LOG = "_cleanup.tsv"
BACKUP_LOG_HEADER = ["timestamp", "removed", "kept", "oldest_kept"]


def _snapshot(name: str) -> tuple[datetime | None, str]:
    """Split a snapshot folder name into (taken at, action it preceded).

    The age is read from the name and not from mtime, because copytree copies
    the source folder's timestamps onto the copy: a backup's mtime is the
    client folder's, not the moment of the backup.

    A name that does not parse yields (None, "") and is therefore never a
    candidate for deletion -- anything in this folder that we did not write
    ourselves is somebody else's, and removing it is not our decision.
    """
    bits = name.split("-")
    if len(bits) < 3:
        return None, ""
    try:
        when = datetime.strptime("-".join(bits[:3]), "%Y%m%d-%H%M%S-%f")
    except ValueError:
        return None, ""
    return when, "-".join(bits[3:])


def prune_backups(root: Path, slug: str, now: datetime | None = None) -> int:
    """Drop backups this client no longer needs. Per client, never global."""
    folder = root / "backups" / one_segment(slug)
    if not folder.is_dir():
        return 0
    snaps = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name)
    cutoff = (now or datetime.now()) - timedelta(days=BACKUP_KEEP_DAYS)

    removed = 0
    for p in snaps[:max(0, len(snaps) - BACKUP_KEEP_COUNT)]:
        when, action = _snapshot(p.name)
        if when is None or when >= cutoff or action in BACKUP_KEEP_ALWAYS:
            continue
        try:
            shutil.rmtree(p)
        except OSError:
            # Locked by a virus scanner or an open Excel: housekeeping must
            # not fail somebody's write. The next one tries again, and the
            # journal below reports what actually went, not what was planned.
            continue
        removed += 1

    if removed:
        # Not changelog.tsv: that file holds the client's facts, and where
        # the program keeps its own copies is not one of them. Local time,
        # to match the snapshot names this line is about.
        left = sorted(p.name for p in folder.iterdir() if p.is_dir())
        append_tsv(folder / BACKUP_LOG, BACKUP_LOG_HEADER, [[
            datetime.now().isoformat(timespec="seconds"),
            removed, len(left), left[0] if left else "",
        ]])
    return removed


# ------------------------------------------------------------- transaction ---

class Tx:
    def __init__(self, root: Path, slug: str, action: str):
        self.root, self.slug, self.action = root, slug, action
        self.entries: list[list[str]] = []

    def log(self, asset_id: str = "", field: str = "",
            old: Any = "", new: Any = "") -> None:
        self.entries.append([
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            getpass.getuser(), self.action, asset_id, field, str(old), str(new),
        ])


@contextmanager
def transaction(root: Path, slug: str, action: str) -> Iterator[Tx]:
    src = mutate_folder(root, slug)
    # The action is part of the folder name so that a snapshot says what it
    # preceded -- both for the person hunting "the state before I deleted
    # that card" and for the keep-always rule above, which has nothing else
    # to go on. Older snapshots carry no suffix and are ordinary ones.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = root / "backups" / slug / f"{stamp}-{action}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Cleaning BEFORE the copy, never after: this transaction's own snapshot
    # is what the rollback below restores from, and it must never be a
    # candidate for deletion.
    prune_backups(root, slug)
    shutil.copytree(src, dest)

    tx = Tx(root, slug, action)
    try:
        yield tx
        # The store must still parse AND still compute. Parsing alone is not
        # enough: an election above the ceiling reads back fine but breaks
        # every report until someone edits the file by hand.
        data = load_client(root, slug)
        closed = data.closed_years()
        for st in data.statuses:
            if st.year not in closed:
                compute_year(data, st.year)
    except BaseException:
        for item in src.iterdir():       # roll back to the backup
            if item.is_file():
                item.unlink()
        for item in dest.iterdir():
            shutil.copy2(item, src / item.name)
        raise

    if tx.entries:
        path = src / "changelog.tsv"
        existing = read_tsv(path)
        header = HEADERS["changelog.tsv"]
        out = [[r.get(h, "") for h in header] for r in existing]
        out.extend(tx.entries)
        write_tsv(path, header, out)


# ---------------------------------------------------------------- checking ---

def guard_open_year(root: Path, slug: str, year: int) -> None:
    """Closed years are sealed: their return has been filed (§6)."""
    if year in load_client(root, slug).closed_years():
        raise DataError(
            f"{year} ili bağlıdır — bəyannamə təqdim edilib, dəyişiklik qəbul "
            f"edilmir (CLAUDE.md §6)"
        )
def _recompute_everything(root: Path) -> None:
    """A rate change touches every client, so every client must still compute.

    `list_clients` comes from the module header. It used to be imported here
    as `from .storage import ...`, which meant engine.storage while this was
    one file and started meaning engine.mutate.storage the moment it became a
    package -- so every norm edit raised ModuleNotFoundError. Mechanical moves
    are safe only where the suite looks (§11); it did not look here, and now
    it does (test_storage.OwnerNorms).
    """
    rates.refresh(root)
    for s in list_clients(root):
        data = load_client(root, s)
        closed = data.closed_years()
        for st in data.statuses:
            if st.year not in closed:
                compute_year(data, st.year)

