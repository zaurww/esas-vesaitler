"""Files, transactions and the closed-year guard.

The four steps every write goes through live here: back the folder up, apply
the change, re-read and recompute the whole store, roll back if it no longer
computes (CLAUDE.md §8.1). Everything else in this package is an action that
runs inside `transaction`."""

from __future__ import annotations

import getpass
import os
import shutil
import tempfile
import tomllib
import uuid

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from .. import rates
from ..calc import compute_year, money
from ..storage import (
    DataError, append_tsv, client_folder, clients_root, list_clients,
    load_client, one_segment, read_tsv, write_tsv,
)
from .parse import _toml_str

HEADERS: dict[str, list[str]] = {
    # e_qaime / serial_no were appended, never inserted: a new optional column
    # leaves format_version alone (§7), and an older engine reading this file
    # simply ignores it -- which is safe here precisely because neither figure
    # enters the calculation.
    "assets.tsv": ["asset_id", "inv_no", "name", "category", "in_date", "cost",
                   "counterparty", "useful_life", "is_legacy_pool", "note",
                   "e_qaime", "serial_no", "group_id"],
    # The client's own classification (§13.1). A dictionary file rather than a
    # name on the card: renaming is then one edit, and a typo cannot quietly
    # split a group in two. Appended like the columns above -- an older engine
    # ignoring it changes no figure, because no figure depends on it.
    "groups.tsv": ["group_id", "name", "note"],
    "opening_balances.tsv": ["year", "asset_id", "category", "residual", "source",
                             "engine_version", "closed_at"],
    "disposals.tsv": ["asset_id", "date", "type", "proceeds"],
    # entry_id appended (§7): rows used to be addressed by (asset_id, date),
    # and two entries on one date were indistinguishable -- see
    # storage.entry_id_of. Ignoring it changes no figure.
    "repairs.tsv": ["year", "asset_id", "date", "amount", "note", "entry_id"],
    "additions.tsv": ["year", "asset_id", "date", "amount", "note", "entry_id"],
    "taxpayer_status.tsv": ["year", "status", "basis", "use_coefficient"],
    "rate_elections.tsv": ["year", "category", "applied_rate", "asset_id"],
    "writeoffs.tsv": ["year", "asset_id", "reason"],
    "changelog.tsv": ["timestamp", "user", "action", "asset_id", "field",
                      "old_value", "new_value"],
}


def mutate_folder(root: Path, slug: str) -> Path:
    f = client_folder(root, slug)
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


def _backup_key(root: Path, slug: str) -> str:
    """The directory a client's backups live under -- `client_id`, not
    `slug` (§3, §8.3).

    Backups used to be keyed by slug because slug was, at the time, the only
    name a client had and it lived in exactly one place: `clients/<slug>/`.
    Once a client folder is free to live anywhere on disk, slug is only a
    display name again -- two folders in two different places can carry the
    same one -- so it stops being safe as a key into a shared directory.

    A client that predates `client_id` gets one here, the first time it is
    next written: generated, persisted into its `config.toml`, and any
    backup history already sitting under the old slug-keyed folder is
    carried over to the new id-keyed one rather than left orphaned. This is
    a narrow, idempotent bootstrap step -- once `client_id` is set it is
    never touched again -- so it runs ahead of the transaction's own
    backup-and-rollback machinery rather than inside it.
    """
    folder = client_folder(root, slug)
    cfg_path = folder / "config.toml"
    text = cfg_path.read_text(encoding="utf-8-sig")
    cfg = tomllib.loads(text)
    cid = str(cfg.get("client_id", "")).strip()
    if cid:
        return cid

    cid = uuid.uuid4().hex
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="\n", delete=False, dir=str(folder))
    try:
        tmp.write(text.rstrip("\n") + f"\nclient_id = {_toml_str(cid)}\n")
        tmp.close()
        os.replace(tmp.name, cfg_path)
    except BaseException:
        os.unlink(tmp.name)
        raise

    old = root / "backups" / one_segment(slug)
    new = root / "backups" / one_segment(cid)
    if old.is_dir() and not new.exists():
        try:
            old.rename(new)
        except OSError:
            # Same tolerance as prune_backups below: a locked folder must not
            # fail somebody's write. New backups go to the new key from here
            # on; the old ones stay findable under the old one, unmerged.
            pass
    return cid


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
    folder = root / "backups" / one_segment(_backup_key(root, slug))
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


# ------------------------------------------------- interrupted transactions ---
#
# Each file is written atomically (temp + os.replace), but an action that
# touches several files is not: a crash or a power cut between assets.tsv and
# opening_balances.tsv used to leave the folder half-written, and the backup
# that could repair it just sat there -- nothing restored it unless somebody
# knew to. So a transaction now leaves a marker in the client folder for as
# long as it runs, naming its own snapshot. A marker that outlives its process
# means that process died mid-write, and the next start restores the snapshot.

TX_MARKER = ".tx_pending"


def _restore(src: Path, snapshot: Path) -> None:
    """Put the folder back exactly as the snapshot holds it.

    Idempotent, and the marker is removed LAST: a crash halfway through a
    restore leaves the marker standing, so the next start simply restores
    again. Each file lands by temp + os.replace, never "delete, then copy",
    which was how the old rollback could leave a file missing altogether.
    """
    keep = {p.name for p in snapshot.iterdir() if p.is_file()}
    for item in snapshot.iterdir():
        if not item.is_file():
            continue
        tmp = src / f".{item.name}.restore"
        shutil.copy2(item, tmp)
        os.replace(tmp, src / item.name)
    for item in src.iterdir():
        if item.is_file() and item.name not in keep and item.name != TX_MARKER:
            item.unlink()
    marker = src / TX_MARKER
    if marker.exists():
        marker.unlink()


def recover_interrupted(root: Path) -> list[str]:
    """Restore every client whose last write never finished. Returns slugs.

    Called at start-up (web server and CLI), before anything reads a client.
    A marker naming a snapshot that does not exist is not something to guess
    around -- it raises, because the folder may be half-written (§2.1).
    """
    recovered: list[str] = []
    base = clients_root(root)
    if not base.is_dir():
        return recovered
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        marker = folder / TX_MARKER
        if not marker.exists():
            continue
        rel = marker.read_text(encoding="utf-8").strip()
        snapshot = (root / rel).resolve()
        if (not rel or (root / "backups").resolve() not in snapshot.parents
                or not snapshot.is_dir()):
            raise DataError(
                f"{folder.name}: yarımçıq qalmış yazı aşkar edildi, lakin onun "
                f"ehtiyat nüsxəsi tapılmadı ({rel!r}). Qovluq yarımçıq ola "
                f"bilər — backups/ qovluğundan son nüsxəni əl ilə bərpa edin."
            )
        _restore(folder, snapshot)
        recovered.append(folder.name)
    return recovered


@contextmanager
def transaction(root: Path, slug: str, action: str) -> Iterator[Tx]:
    src = mutate_folder(root, slug)
    if (src / TX_MARKER).exists():
        # A previous write in some other process died on this client. Writing
        # on top of a half-written folder would make the damage permanent.
        recover_interrupted(root)
    # Keyed by client_id, not slug (§3, §8.3) -- generated and persisted here
    # if this client predates it, carrying its backup history to the new key.
    client_id = _backup_key(root, slug)
    # The action is part of the folder name so that a snapshot says what it
    # preceded -- both for the person hunting "the state before I deleted
    # that card" and for the keep-always rule above, which has nothing else
    # to go on. Older snapshots carry no suffix and are ordinary ones.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = root / "backups" / one_segment(client_id) / f"{stamp}-{action}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Cleaning BEFORE the copy, never after: this transaction's own snapshot
    # is what the rollback below restores from, and it must never be a
    # candidate for deletion.
    prune_backups(root, slug)
    shutil.copytree(src, dest)
    # Written after the copy, so the snapshot never contains it; removed only
    # once the write -- changelog included -- has fully landed.
    (src / TX_MARKER).write_text(dest.relative_to(root).as_posix(),
                                 encoding="utf-8")

    tx = Tx(root, slug, action)
    try:
        yield tx
        # The store must still parse AND still compute. Parsing alone is not
        # enough: an election above the ceiling reads back fine but breaks
        # every report until someone edits the file by hand.
        data = load_client(root, slug)
        closed = data.closed_years()
        cache: dict = {}
        for st in sorted(data.statuses, key=lambda s: s.year):
            if st.year not in closed:
                compute_year(data, st.year, cache)
        # Inside the try: a write whose changelog line failed to land is a
        # write nobody can account for, so it rolls back with the rest.
        if tx.entries:
            path = src / "changelog.tsv"
            existing = read_tsv(path)
            header = HEADERS["changelog.tsv"]
            out = [[r.get(h, "") for h in header] for r in existing]
            out.extend(tx.entries)
            write_tsv(path, header, out)
    except BaseException:
        _restore(src, dest)
        raise
    (src / TX_MARKER).unlink()


# ---------------------------------------------------------------- checking ---

def guard_open_year(root: Path, slug: str, year: int) -> None:
    """Closed years are sealed: their return has been filed (§6)."""
    if year in load_client(root, slug).closed_years():
        raise DataError(
            f"{year} ili bağlıdır — bəyannamə təqdim edilib, dəyişiklik qəbul "
            f"edilmir (CLAUDE.md §6)"
        )


def verify_client(root: Path, slug: str) -> list[dict]:
    """Recompute one client's closed years and diff against their seal.

    Falls straight out of the event-sourced design (§2): a cheap regression
    detector across engine versions. `ev.py verify` has printed this since
    §11.4; the logic moved here, unchanged, so the self-update's post-update
    check (web/app.py, §9) can call the very same thing instead of growing a
    second copy that could drift from it.

    Returns one dict per mismatch (empty means the seal still holds).
    """
    data = load_client(root, slug)
    stored: dict[tuple[int, str], str] = {}
    for row in read_tsv(client_folder(root, slug) / "opening_balances.tsv"):
        if row.get("source") == "year_close":
            stored[(int(row["year"]), row["asset_id"])] = row["residual"].strip()
    mismatches: list[dict] = []
    for year in sorted(data.closed_years()):
        r = compute_year(data, year)
        for c in r.cards:
            key = (year + 1, c.asset_id)
            if key not in stored:
                continue
            recomputed = f"{money(c.closing):.2f}"
            # Decimal, never float (§11) -- the seal is a money figure.
            try:
                sealed = money(Decimal(stored[key]))
            except InvalidOperation:
                raise DataError(f"opening_balances.tsv: {year + 1} "
                                f"{c.asset_id}: qalıq oxunmur: {stored[key]!r}")
            if money(c.closing) != sealed:
                mismatches.append({
                    "client": slug, "year": year, "asset_id": c.asset_id,
                    "stored": stored[key], "recomputed": recomputed,
                })
    return mismatches


def verify_all(root: Path) -> dict[str, list[dict]]:
    """verify_client() for every client this installation holds.

    Only clients WITH a mismatch appear in the result. That matters to the
    caller that matters most here -- the post-update check -- where a clean
    run must read as clean (an empty dict), not as a wall of empty entries
    that looks the same as a wall of real ones (§2.1).
    """
    return {s: bad for s in list_clients(root)
            if (bad := verify_client(root, s))}


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
        cache: dict = {}
        for st in sorted(data.statuses, key=lambda x: x.year):
            if st.year not in closed:
                compute_year(data, st.year, cache)

