"""Files, transactions and the closed-year guard.

The four steps every write goes through live here: back the folder up, apply
the change, re-read and recompute the whole store, roll back if it no longer
computes (CLAUDE.md §8.1). Everything else in this package is an action that
runs inside `transaction`."""

from __future__ import annotations

import getpass
import shutil

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .. import rates
from ..calc import compute_year
from ..storage import DataError, list_clients, load_client, read_tsv, write_tsv

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
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = root / "backups" / slug / stamp
    dest.parent.mkdir(parents=True, exist_ok=True)
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
    """A rate change touches every client, so every client must still compute."""
    from .storage import list_clients
    rates.refresh(root)
    for s in list_clients(root):
        data = load_client(root, s)
        closed = data.closed_years()
        for st in data.statuses:
            if st.year not in closed:
                compute_year(data, st.year)

