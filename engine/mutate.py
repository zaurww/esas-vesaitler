"""Writing to a client folder (CLAUDE.md §8).

Every change goes through `transaction`, which does four things in order:

    1. backs the folder up,
    2. applies the change with atomic per-file writes,
    3. re-reads and re-validates the WHOLE store,
    4. rolls back to the backup if step 3 fails.

Step 3 is the point. Individual field checks cannot catch cross-file damage --
deleting an asset that a balance still points at, for instance -- so instead of
trying to enumerate those cases the store is simply re-parsed after each
change. If it no longer loads, the change never happened.
"""

from __future__ import annotations

import getpass
import io
import re
import shutil
import tomllib
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from .calc import compute_year
from . import rates
from .rates import CATEGORY_BY_CODE, ENGINE_VERSION, FORMAT_VERSION
from .storage import DataError, load_client, read_tsv, write_tsv

D = Decimal

HEADERS: dict[str, list[str]] = {
    "assets.tsv": ["asset_id", "inv_no", "name", "category", "in_date", "cost",
                   "counterparty", "useful_life", "is_legacy_pool", "note"],
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


_NUM_NOISE = re.compile(r"[\s  '`]|AZN|azn|₼")


def _normalise_number(raw: str, field: str) -> str:
    """Turn what Excel puts on the clipboard into something Decimal accepts.

    A pasted money column arrives as the user SEES it -- "1 234,56" here,
    "1,234.56" on an English machine, with non-breaking spaces for grouping.
    Rejecting all of that would make pasting useless, but guessing is worse:
    "1,234" is 1234 in one locale and 1.234 in the other, and quietly picking
    one would store a number a thousand times off. So the unambiguous shapes
    are accepted and the one genuinely ambiguous shape is refused out loud
    (§2.1).
    """
    s = _NUM_NOISE.sub("", raw)
    if not s:
        return "0"
    neg = s.startswith("-")
    s = s.lstrip("+-")
    commas, dots = s.count(","), s.count(".")

    if commas and dots:
        # Both present: whichever comes last is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif commas > 1:
        s = s.replace(",", "")                     # 1,234,567 -- grouping
    elif commas == 1:
        head, _, tail = s.partition(",")
        if len(tail) == 3 and head[-1:].isdigit():
            raise DataError(
                f"{field}: {raw.strip()!r} birmənalı deyil — «,» burada həm "
                f"onluq ayırıcı (1,234 = 1.234), həm də minlik ayırıcı "
                f"(1,234 = 1234) ola bilər. Onluq hissəni nöqtə ilə yazın."
            )
        s = s.replace(",", ".")
    elif dots > 1:
        s = s.replace(".", "")                     # 1.234.567 -- grouping

    try:
        d = D(("-" if neg else "") + s)
    except InvalidOperation:
        raise DataError(f"{field}: rəqəm deyil — {raw.strip()!r}") from None
    return str(d)


def dec(value: Any, field: str, *, allow_zero: bool = True) -> str:
    raw = str(value).strip()
    try:
        d = D(_normalise_number(raw, field) if raw else "0")
    except InvalidOperation:
        raise DataError(f"{field}: rəqəm deyil — {value!r}") from None
    if d < 0 or (not allow_zero and d == 0):
        raise DataError(f"{field}: mənfi və ya sıfır ola bilməz — {d}")
    return f"{d:.2f}"


# Day first, because that is how the date is written here and in the source
# workbooks. Deliberately NOT accepting %m/%d/%Y: "03/05/2023" would then be
# two different dates depending on which pattern matched first, and nothing in
# the cell says which was meant.
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


def iso_date(value: Any, field: str, *, required: bool = True) -> str:
    v = str(value or "").strip()
    if not v:
        if required:
            raise DataError(f"{field}: tarix tələb olunur")
        return ""
    # Excel hands over a datetime as "15.02.2023 0:00" -- drop the time.
    v = v.split()[0] if " " in v else v
    v = v.replace("T", " ").split()[0]
    d = None
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(v, fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        raise DataError(
            f"{field}: tarix anlaşılmadı — {value!r}. "
            f"YYYY-MM-DD və ya GG.AA.YYYY yazın."
        )
    if d > date.today():
        raise DataError(f"{field}: gələcək tarix ola bilməz — {d}")
    return d.isoformat()


def category_of(value: Any, field: str = "category") -> str:
    v = str(value or "").strip()
    if v not in CATEGORY_BY_CODE:
        raise DataError(f"{field}: naməlum kateqoriya {v!r}")
    return v


INV_PATTERN = re.compile(r"^(.*?)(\d+)$")


def suggest_inv_no(rows: list[dict[str, str]], category: str) -> str:
    """Propose the next inventory number, following whatever the client
    already uses rather than imposing a scheme.

    Numbering conventions differ per office and often arrive from 1C, so the
    prevailing prefix and zero-padding of that category are copied and the
    counter is stepped. Only when a category has none does it fall back to
    <CATEGORY>-0001. The suggestion is always editable -- it is a convenience,
    not a rule.
    """
    used = {r.get("inv_no", "").strip() for r in rows if r.get("inv_no", "").strip()}
    prefixes: dict[tuple[str, int], int] = {}
    for r in rows:
        if r.get("category") != category:
            continue
        m = INV_PATTERN.match(r.get("inv_no", "").strip())
        if m:
            key = (m.group(1), len(m.group(2)))
            prefixes[key] = max(prefixes.get(key, 0), int(m.group(2)))

    if prefixes:
        (prefix, width), top = max(prefixes.items(), key=lambda kv: (kv[1], kv[0][1]))
    else:
        prefix, width, top = f"{category.upper()}-", 4, 0

    n = top + 1
    while f"{prefix}{n:0{width}d}" in used:
        n += 1
    return f"{prefix}{n:0{width}d}"


def inv_series(rows: list[dict[str, str]], first: str, count: int) -> list[str]:
    """`count` inventory numbers, stepping the counter of `first`.

    Derived once from the starting number rather than by asking
    suggest_inv_no() again for every card. That function follows the prefix
    already prevailing in the category, so the moment a batch introduces a new
    one, the second call would jump back to whichever prefix holds the higher
    counter -- an MA-0008 landing in the middle of XOL-0001…XOL-0240.

    A starting number with no digits to step ("XOL") gets a counter appended;
    otherwise the numbers would collide and inv_no has to stay unique (§4).
    """
    used = {r.get("inv_no", "").strip() for r in rows if r.get("inv_no", "").strip()}
    m = INV_PATTERN.match(first)
    if m:
        prefix, width, n = m.group(1), len(m.group(2)), int(m.group(2))
    else:
        prefix, width, n = f"{first}-", 4, 1
    out: list[str] = []
    for _ in range(count):
        while f"{prefix}{n:0{width}d}" in used:
            n += 1
        number = f"{prefix}{n:0{width}d}"
        used.add(number)
        out.append(number)
        n += 1
    return out


ASSET_ID_FMT = "AV-{:03d}"


def next_asset_id(rows: list[dict[str, str]]) -> str:
    n = 0
    for r in rows:
        aid = r.get("asset_id", "")
        if aid.startswith("AV-") and aid[3:].isdigit():
            n = max(n, int(aid[3:]))
    return ASSET_ID_FMT.format(n + 1)


def asset_id_series(rows: list[dict[str, str]], count: int) -> list[str]:
    """`count` fresh ids in one pass.

    Asking for "the next id" once per card would rescan every row each time,
    turning a 240-card purchase into a quadratic walk for nothing.
    """
    start = int(next_asset_id(rows)[3:])
    return [ASSET_ID_FMT.format(start + i) for i in range(count)]


# A slipped digit turns 240 into 2400, and the guard is here rather than in the
# page because the page is not the only way in. Not a figure of the law, so it
# stays in code (§5.1-bis draws that line at what the tax code sets).
BATCH_MAX = 2000


def batch_count(value: Any) -> int:
    """How many identical cards this purchase creates.

    One card per physical object, always -- and not out of tidiness. The law
    tests per object: 240 refrigerators at 400 AZN each drop under the 114.8
    threshold one by one, while a single 96 000 AZN line never would, and a
    sale of three of them has to remove the residual of exactly those three
    (114.6). A quantity column would quietly cost the client the deduction.

    So the count belongs to the FORM, not to the data: it expands into rows
    here and is stored nowhere (§2 -- the fact is that 240 objects arrived).
    """
    raw = str(value or "").strip()
    if not raw:
        return 1
    if not raw.isdigit():
        raise DataError(f"Say tam ədəd olmalıdır, {raw!r} deyil")
    n = int(raw)
    if n < 1:
        raise DataError("Say ən azı 1 olmalıdır")
    if n > BATCH_MAX:
        raise DataError(
            f"Say {n} — səhv yazılış kimi görünür (maksimum {BATCH_MAX}). "
            f"Doğrudan bu qədərdirsə, alışı hissələrə bölün."
        )
    return n


# ----------------------------------------------------------------- actions ---

MODES = ("new", "carried", "pool")


def create_asset(root: Path, slug: str, p: dict) -> str:
    """Three ways an asset enters the books.

    `new`      bought during the open year -- date and cost are known.
    `carried`  already on the books when the client arrived; the opening
               residual comes from their last filed return. Initial cost may
               be unknown, in which case only the 500 AZN half of the
               threshold test can ever apply to it.
    `pool`     the client could only give GROUP totals, not a breakdown per
               asset. One card per category carries the group residual
               (§6.1). No inventory number, no date, no initial cost.

    `say` buys the same thing many times over: cost is per unit, and the whole
    batch is written in ONE transaction. Not for speed -- §8.1 backs up the
    client folder and recomputes every open year on each write, so 240 separate
    calls would mean 240 backups and 240 recomputations for what the accountant
    did once. Same reasoning as set_writeoff taking a list (§5.3-bis).
    """
    mode = str(p.get("mode", "new"))
    if mode not in MODES:
        raise DataError(f"naməlum rejim: {mode!r}")
    category = category_of(p.get("category"))
    residual = str(p.get("opening_residual", "")).strip()
    count = batch_count(p.get("say"))
    if mode == "pool" and count > 1:
        # A pool is one card standing for a group that HAS no cards. Asking for
        # 240 of them is asking for the same total 240 times over.
        raise DataError("Qrup qalığı kartsız cəmdir — say tətbiq edilmir")

    with transaction(root, slug, "asset.create") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        inv = str(p.get("inv_no", "")).strip()
        if inv and any(r["inv_no"] == inv for r in assets):
            raise DataError(f"inv_no {inv!r} artıq mövcuddur")

        if mode == "pool":
            name = str(p.get("name", "")).strip() or \
                f"{CATEGORY_BY_CODE[category].name_az} — qrup qalığı"
            inv, in_date, cost = "", "", "0.00"
            if not residual:
                raise DataError("Qrup qalığı üçün qalıq dəyər tələb olunur")
        else:
            name = str(p.get("name", "")).strip()
            if not name:
                raise DataError("Adı boş ola bilməz")
            in_date = iso_date(p.get("in_date"), "Alış tarixi",
                               required=(mode == "new"))
            cost = dec(p.get("cost"), "İlkin dəyər",
                       allow_zero=(mode == "carried"))
            if mode == "new" and D(cost) == 0:
                raise DataError("İlkin dəyər sıfır ola bilməz")
            if mode == "carried" and not residual:
                raise DataError("Əvvəlki illərdən gələn ƏV üçün qalıq dəyər "
                                "tələb olunur")

        if mode == "pool":
            numbers = [""]
        else:
            # An asset with no inventory number is a defect, not a choice --
            # it is how the physical object is identified. Fill it in from the
            # scheme already in use rather than leaving a silent hole. A group
            # residual is the one legitimate exception: nothing to label.
            numbers = inv_series(assets, inv or suggest_inv_no(assets, category),
                                 count)
        ids = asset_id_series(assets, len(numbers))

        year = 0
        ob: list[dict[str, str]] = []
        if residual:
            # Checked before a single row is written: the transaction would
            # roll back anyway, but failing first says so without the detour.
            year = int(p["opening_year"])
            guard_open_year(root, slug, year)
            ob = rows_of(root, slug, "opening_balances.tsv")

        for aid, number in zip(ids, numbers):
            assets.append({
                "asset_id": aid, "inv_no": number, "name": name,
                "category": category, "in_date": in_date, "cost": cost,
                "counterparty": str(p.get("counterparty", "")).strip(),
                "useful_life": str(p.get("useful_life", "")).strip(),
                "is_legacy_pool": "1" if mode == "pool" else "",
                "note": str(p.get("note", "")).strip(),
            })
            # One changelog line per object even though the act was one. The
            # grouping was for the person doing the work, not an excuse to
            # record less of what happened (§5.3-bis).
            tx.log(aid, "asset", "", f"[{mode}] {number} {name}".strip())
            if residual:
                _apply_opening(ob, aid, category, year, residual, tx)

        save_rows(root, slug, "assets.tsv", assets)
        if residual:
            save_rows(root, slug, "opening_balances.tsv", ob)

    if count == 1:
        return ids[0]
    return (f"{count} kart yaradıldı: {numbers[0]} … {numbers[-1]} — "
            f"hər biri {cost} AZN")


def update_asset(root: Path, slug: str, p: dict) -> str:
    aid = str(p["asset_id"])
    with transaction(root, slug, "asset.update") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        row = next((r for r in assets if r["asset_id"] == aid), None)
        if row is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        new = {
            "inv_no": str(p.get("inv_no", "")).strip(),
            "name": str(p.get("name", "")).strip(),
            "category": category_of(p.get("category")),
            "in_date": iso_date(p.get("in_date"), "Alış tarixi"),
            "cost": dec(p.get("cost"), "İlkin dəyər"),
            "counterparty": str(p.get("counterparty", "")).strip(),
            "note": str(p.get("note", "")).strip(),
        }
        if new["inv_no"] and any(
                r["inv_no"] == new["inv_no"] and r["asset_id"] != aid for r in assets):
            raise DataError(f"inv_no {new['inv_no']!r} artıq mövcuddur")
        if not new["name"]:
            raise DataError("Adı boş ola bilməz")
        for field, value in new.items():
            if row[field] != value:
                tx.log(aid, field, row[field], value)
                row[field] = value
        save_rows(root, slug, "assets.tsv", assets)

        # The category lives on the balance rows too; keep them in step.
        ob = rows_of(root, slug, "opening_balances.tsv")
        for r in ob:
            if r["asset_id"] == aid and r["category"] != new["category"]:
                r["category"] = new["category"]

        # The opening residual is edited from this same form now. It used to
        # be reachable only from a second button, which meant a residual typed
        # wrong during import looked uncorrectable: the number was on screen,
        # the edit form did not have it, and nobody guessed that "Açılış
        # qalığı" next door was the way in.
        #
        # `opening_edit` is what the form ticks when it actually showed the
        # field, so an empty value means "delete this year's row" rather than
        # "the caller did not mention it". The form only shows the field for a
        # residual that IS an explicit fact: a balance carried from last year
        # is computed (§2, §6.1), and prefilling a computed number into a form
        # would freeze it into stored data the moment someone pressed save --
        # the same trap the norms form fell into (§5.1).
        if p.get("opening_edit"):
            year = int(p["opening_year"])
            guard_open_year(root, slug, year)
            _apply_opening(ob, aid, new["category"], year,
                           str(p.get("opening_residual", "")).strip(), tx)
        save_rows(root, slug, "opening_balances.tsv", ob)
    return aid


def delete_asset(root: Path, slug: str, p: dict) -> str:
    """Delete the asset AND everything that references it.

    Removing only the card is what left an orphaned opening balance behind
    when the files were edited by hand.
    """
    aid = str(p["asset_id"])
    with transaction(root, slug, "asset.delete") as tx:
        for name in ("opening_balances.tsv", "disposals.tsv", "repairs.tsv",
                     "additions.tsv", "writeoffs.tsv", "rate_elections.tsv"):
            rows = rows_of(root, slug, name)
            kept = [r for r in rows if r.get("asset_id") != aid]
            if len(kept) != len(rows):
                tx.log(aid, name, f"{len(rows) - len(kept)} sətir", "silindi")
                save_rows(root, slug, name, kept)
        assets = rows_of(root, slug, "assets.tsv")
        row = next((r for r in assets if r["asset_id"] == aid), None)
        if row is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        tx.log(aid, "asset", f"{row['inv_no']} {row['name']}", "silindi")
        save_rows(root, slug, "assets.tsv",
                  [r for r in assets if r["asset_id"] != aid])
    return aid


def _apply_opening(rows: list[dict[str, str]], aid: str, category: str,
                   year: int, value: str, tx: "Tx") -> None:
    """Set, change or drop the explicit opening balance of one asset-year.

    Three callers write this row -- creating a card, editing one, and the
    dedicated form -- and they must agree on what an empty value means and on
    what lands in the changelog, so the rule lives here once.
    """
    old = next((r for r in rows
                if r["asset_id"] == aid and r["year"] == str(year)), None)
    if value == "":
        if old:
            rows.remove(old)
            tx.log(aid, f"opening_balance {year}", old["residual"], "silindi")
        return
    v = dec(value, "Qalıq dəyər")
    if old:
        if old["residual"] != v:
            tx.log(aid, f"opening_balance {year}", old["residual"], v)
            old["residual"] = v
    else:
        rows.append({"year": str(year), "asset_id": aid, "category": category,
                     "residual": v, "source": "onboarding",
                     "engine_version": "", "closed_at": ""})
        tx.log(aid, f"opening_balance {year}", "", v)


def set_opening(root: Path, slug: str, p: dict) -> str:
    aid, year = str(p["asset_id"]), int(p["year"])
    with transaction(root, slug, "opening.set") as tx:
        guard_open_year(root, slug, year)
        assets = rows_of(root, slug, "assets.tsv")
        asset = next((r for r in assets if r["asset_id"] == aid), None)
        if asset is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        rows = rows_of(root, slug, "opening_balances.tsv")
        _apply_opening(rows, aid, asset["category"], year,
                       str(p.get("residual", "")).strip(), tx)
        save_rows(root, slug, "opening_balances.tsv", rows)
    return aid


def set_disposal(root: Path, slug: str, p: dict) -> str:
    aid = str(p["asset_id"])
    with transaction(root, slug, "disposal.set") as tx:
        rows = rows_of(root, slug, "disposals.tsv")
        rows = [r for r in rows if r["asset_id"] != aid]
        if not p.get("remove"):
            when = iso_date(p.get("date"), "Xaricetmə tarixi")
            guard_open_year(root, slug, int(when[:4]))
            typ = str(p.get("type", "")).strip()
            if typ not in ("realizasiya", "leqv"):
                raise DataError("Xaricetmə növü: realizasiya | leqv")
            rows.append({"asset_id": aid, "date": when, "type": typ,
                         "proceeds": dec(p.get("proceeds"), "Satış məbləği")})
            tx.log(aid, "disposal", "", f"{when} {typ}")
        else:
            tx.log(aid, "disposal", "var", "silindi")
        save_rows(root, slug, "disposals.tsv", rows)
    return aid


def add_repair(root: Path, slug: str, p: dict) -> str:
    aid = str(p["asset_id"])
    with transaction(root, slug, "repair.add") as tx:
        when = iso_date(p.get("date"), "Təmir tarixi")
        year = int(when[:4])
        guard_open_year(root, slug, year)
        amount = dec(p.get("amount"), "Məbləğ", allow_zero=False)
        rows = rows_of(root, slug, "repairs.tsv")
        rows.append({"year": str(year), "asset_id": aid, "date": when,
                     "amount": amount, "note": str(p.get("note", "")).strip()})
        save_rows(root, slug, "repairs.tsv", rows)
        tx.log(aid, f"repair {when}", "", amount)
    return aid


def remove_repair(root: Path, slug: str, p: dict) -> str:
    aid, when = str(p["asset_id"]), str(p["date"])
    with transaction(root, slug, "repair.remove") as tx:
        guard_open_year(root, slug, int(when[:4]))
        rows = rows_of(root, slug, "repairs.tsv")
        kept = [r for r in rows if not (r["asset_id"] == aid and r["date"] == when)]
        tx.log(aid, f"repair {when}", "var", "silindi")
        save_rows(root, slug, "repairs.tsv", kept)
    return aid


def _toml_str(value: str) -> str:
    """Quote a value for config.toml. A client name legitimately contains
    «» and " -- unescaped it produced a file tomllib then refused to read."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_client(root: Path, slug: str, p: dict) -> str:
    """Edit the client's own details: name, VÖEN, first year.

    There was no way to do this at all -- the creation form asked once and
    that was final, so a typo in the name or the wrong VÖEN was permanent.

    The folder name is NOT among them. It is the client's identity: every
    backup, archive and URL carries it, and renaming it here would leave
    those pointing at nothing. Moving to a different name is export/import.
    """
    folder = mutate_folder(root, slug)
    cfg = tomllib.loads((folder / "config.toml").read_text(encoding="utf-8-sig"))
    name = str(p.get("client_name", cfg.get("client_name", ""))).strip()
    if not name:
        raise DataError("Müştərinin adı boş ola bilməz")
    voen = str(p.get("voen", cfg.get("voen", ""))).strip()
    try:
        year = int(p.get("start_year") or cfg.get("start_year"))
    except (TypeError, ValueError):
        raise DataError("İl düzgün deyil") from None
    if not (1990 < year < 2100):
        raise DataError(f"Başlanğıc il düzgün deyil: {year}")

    with transaction(root, slug, "client.update") as tx:
        for field, old, new in (("client_name", cfg.get("client_name", ""), name),
                                ("voen", cfg.get("voen", ""), voen),
                                ("start_year", str(cfg.get("start_year", "")), str(year))):
            if str(old) != str(new):
                tx.log("", field, str(old), str(new))
        (folder / "config.toml").write_text(
            f"client_name = {_toml_str(name)}\n"
            f"voen = {_toml_str(voen)}\n"
            f"start_year = {year}\n"
            f"format_version = {cfg.get('format_version', FORMAT_VERSION)}\n",
            encoding="utf-8-sig", newline="\n",
        )
    return slug


def add_addition(root: Path, slug: str, p: dict) -> str:
    """Capitalise a component or upgrade onto an existing asset."""
    aid = str(p["asset_id"])
    with transaction(root, slug, "addition.add") as tx:
        when = iso_date(p.get("date"), "Tarix")
        year = int(when[:4])
        guard_open_year(root, slug, year)
        amount = dec(p.get("amount"), "Məbləğ", allow_zero=False)
        rows = rows_of(root, slug, "additions.tsv")
        rows.append({"year": str(year), "asset_id": aid, "date": when,
                     "amount": amount, "note": str(p.get("note", "")).strip()})
        save_rows(root, slug, "additions.tsv", rows)
        tx.log(aid, f"addition {when}", "", amount)
    return aid


def remove_addition(root: Path, slug: str, p: dict) -> str:
    aid, when = str(p["asset_id"]), str(p["date"])
    with transaction(root, slug, "addition.remove") as tx:
        guard_open_year(root, slug, int(when[:4]))
        rows = rows_of(root, slug, "additions.tsv")
        kept = [r for r in rows
                if not (r["asset_id"] == aid and r["date"] == when)]
        tx.log(aid, f"addition {when}", "var", "silindi")
        save_rows(root, slug, "additions.tsv", kept)
    return aid


SLUG_MAP = str.maketrans({
    "ə": "e", "ç": "c", "ş": "s", "ğ": "g", "ı": "i", "ö": "o", "ü": "u",
    "Ə": "e", "Ç": "c", "Ş": "s", "Ğ": "g", "İ": "i", "Ö": "o", "Ü": "u",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "c", "ч": "c", "ш": "s", "щ": "s", "ы": "i", "э": "e",
    "ю": "u", "я": "a", "ъ": "", "ь": "",
})


def slugify(name: str) -> str:
    """Folder name from a company name. ASCII only: the folder is a path on
    someone else's Windows machine, and it is also the client's id in URLs."""
    s = str(name or "").strip().lower().translate(SLUG_MAP)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "musteri"


def create_client(root: Path, _slug: str, p: dict) -> str:
    """Create a client folder with every file the engine expects.

    A fresh install has no clients and no way to make one, which left the
    worker looking at an empty screen on day one. The files are created here,
    with headers only, so the store is valid from the first second rather
    than materialising piece by piece as features get used.
    """
    name = str(p.get("client_name", "")).strip()
    if not name:
        raise DataError("Müştərinin adı boş ola bilməz")
    voen = str(p.get("voen", "")).strip()
    try:
        year = int(p.get("start_year") or 0)
    except ValueError:
        raise DataError("İl düzgün deyil") from None
    if not (1990 < year < 2100):
        raise DataError(f"Başlanğıc il düzgün deyil: {p.get('start_year')!r}")
    status = str(p.get("status", "orta")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")

    slug = slugify(p.get("slug") or name)
    folder = root / "clients" / slug
    if folder.exists():
        raise DataError(f"«{slug}» qovluğu artıq mövcuddur")
    folder.mkdir(parents=True)

    try:
        (folder / "config.toml").write_text(
            f"client_name = {_toml_str(name)}\n"
            f"voen = {_toml_str(voen)}\n"
            f"start_year = {year}\n"
            f"format_version = {FORMAT_VERSION}\n",
            encoding="utf-8-sig", newline="\n",
        )
        for fname, header in HEADERS.items():
            write_tsv(folder / fname, header, [])
        # A year with no taxpayer status cannot be computed, so seed the one
        # the client starts in -- otherwise the first screen is an error.
        save_rows(root, slug, "taxpayer_status.tsv",
                  [{"year": str(year), "status": status, "basis": "",
                    "use_coefficient": ""}])
        save_rows(root, slug, "changelog.tsv", [{
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user": getpass.getuser(), "action": "client.create",
            "asset_id": "", "field": "client", "old_value": "",
            "new_value": f"{name} ({slug})",
        }])
        load_client(root, slug)          # must parse before we hand it back
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return slug



# --- moving a client between machines --------------------------------------
# Copying the folder is not enough, and the ways it goes wrong are silent:
#
#   * the norms in rates.tsv / coefficients.tsv live NEXT TO THE ENGINE, not
#     in the client folder. A client carried alone lands on the target
#     machine's norms and quietly computes different numbers.
#   * an older engine on the target machine does not know files added later
#     (additions.tsv, and columns like use_coefficient). It does not fail --
#     it just does not read them, and the result is off with no error.
#
# So an archive carries the norms and records which engine wrote the data,
# and the import compares before it writes.

ARCHIVE_MANIFEST = "manifest.json"


def export_client(root: Path, slug: str) -> bytes:
    import hashlib
    import json
    import zipfile

    folder = mutate_folder(root, slug)
    data = load_client(root, slug)
    buf = io.BytesIO()
    files = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix not in (".tsv", ".toml"):
                continue
            raw = f.read_bytes()
            files[f.name] = hashlib.sha256(raw).hexdigest()
            z.writestr(f"client/{f.name}", raw)
        for name in rates.NORM_FILES:
            p = root / name
            if p.exists():
                z.writestr(f"norms/{name}", p.read_bytes())
        z.writestr(ARCHIVE_MANIFEST, json.dumps({
            "slug": slug,
            "client_name": data.client_name,
            "voen": data.voen,
            "engine_version": ENGINE_VERSION,
            "format_version": data.format_version,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "exported_by": getpass.getuser(),
            "files": files,
        }, ensure_ascii=False, indent=2))
    return buf.getvalue()


def inspect_archive(root: Path, blob: bytes) -> dict:
    """Read the archive and say what importing it would mean, without writing."""
    import json
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(blob))
    try:
        man = json.loads(z.read(ARCHIVE_MANIFEST).decode("utf-8"))
    except KeyError:
        raise DataError("Bu arxiv proqram tərəfindən yaradılmayıb "
                        "(manifest.json yoxdur)") from None

    notes, blocking = [], []
    if _version_tuple(man["engine_version"]) > _version_tuple(ENGINE_VERSION):
        blocking.append(
            f"Arxiv daha yeni mühərriklə ({man['engine_version']}) yazılıb, "
            f"burada {ENGINE_VERSION} var. Əvvəlcə proqramı yeniləyin — köhnə "
            f"mühərrik yeni məlumatın bir hissəsini sadəcə oxumur və rəqəmlər "
            f"səhv çıxır."
        )
    if man["format_version"] != FORMAT_VERSION:
        notes.append(f"Format v{man['format_version']} → v{FORMAT_VERSION}.")

    for name in rates.NORM_FILES:
        try:
            theirs = z.read(f"norms/{name}")
        except KeyError:
            theirs = b""
        p = root / name
        ours = p.read_bytes() if p.exists() else b""
        if theirs.strip() != ours.strip():
            notes.append(
                f"«{name}» fərqlidir: normalar müştəri qovluğunda deyil, "
                f"proqramın yanında saxlanılır. Arxivdəki variantı tətbiq "
                f"etməsəniz, rəqəmlər bu maşında başqa cür çıxacaq."
            )

    # Not blocking: importing under a different name is a normal thing to do,
    # so the collision is reported and the caller picks a target.
    exists = (root / "clients" / man["slug"]).exists()
    if exists:
        notes.append(f"«{man['slug']}» qovluğu artıq mövcuddur — "
                     f"başqa ad seçin.")
    return {"manifest": man, "notes": notes, "blocking": blocking,
            "exists": exists, "suggested_slug": man["slug"]}


def _version_tuple(v: str) -> tuple:
    out = []
    for part in str(v).split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


def import_client(root: Path, _slug: str, p: dict) -> Any:
    import base64
    import json
    import zipfile

    blob = base64.b64decode(p.get("b64", ""))
    info = inspect_archive(root, blob)
    if p.get("dry_run"):
        return info
    if info["blocking"]:
        raise DataError(" ".join(info["blocking"]))

    z = zipfile.ZipFile(io.BytesIO(blob))
    man = info["manifest"]
    # Through slugify, not raw: this is the one place a folder is CREATED from
    # a name the request supplies. Taking it verbatim both broke the ASCII rule
    # of §4 (a Cyrillic "е" produced a folder no URL could carry) and let the
    # path point outside clients/ entirely.
    slug = slugify(p.get("slug") or man["slug"])
    if not slug:
        raise DataError("Qovluq adı boşdur")
    folder = root / "clients" / one_segment(slug)
    if folder.exists():
        raise DataError(f"«{slug}» qovluğu artıq mövcuddur")
    folder.mkdir(parents=True)
    try:
        for entry in z.namelist():
            if entry.startswith("client/") and not entry.endswith("/"):
                (folder / Path(entry).name).write_bytes(z.read(entry))
        if p.get("apply_norms"):
            for name in rates.NORM_FILES:
                try:
                    (root / name).write_bytes(z.read(f"norms/{name}"))
                except KeyError:
                    pass
            rates.refresh(root)
        data = load_client(root, slug)
        closed = data.closed_years()
        for st in data.statuses:
            if st.year not in closed:
                compute_year(data, st.year)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {"slug": slug, "notes": info["notes"]}


def close_year(root: Path, slug: str, p: dict) -> str:
    """Close a year: write its closing balances as next year's opening ones.

    This is the ONLY way balances move between years (CLAUDE.md §6). Nothing
    carries over automatically, because carrying over is what freezes the
    numbers that went into a filed return -- it has to be a deliberate act,
    stamped with who closed it, when, and with which engine version.
    """
    year = int(p["year"])
    data = load_client(root, slug)
    if year in data.closed_years():
        raise DataError(f"{year} ili artıq bağlıdır")
    rates.refresh(root)
    result = compute_year(data, year)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with transaction(root, slug, "year.close") as tx:
        rows = rows_of(root, slug, "opening_balances.tsv")
        n = 0
        for c in result.cards:
            if c.closing == 0 and (c.written_off or c.disposal_type):
                continue                      # the asset has left the books
            rows.append({
                "year": str(year + 1), "asset_id": c.asset_id,
                "category": c.category, "residual": f"{c.closing:.2f}",
                "source": "year_close", "engine_version": ENGINE_VERSION,
                "closed_at": stamp,
            })
            n += 1
        save_rows(root, slug, "opening_balances.tsv", rows)
        tx.log("", f"close {year}", "", f"{n} sətir → {year + 1}")
    return f"{year} → {year + 1}: {n}"


def reopen_year(root: Path, slug: str, p: dict) -> str:
    """Undo a close.

    §6 seals closed years on purpose, but a misclick must not require editing
    files by hand -- that is the very thing the app exists to prevent. The
    reversal is loud: it is named in the changelog, and it throws away the
    stored balances, so the next close recomputes them from scratch.
    """
    year = int(p["year"])
    with transaction(root, slug, "year.reopen") as tx:
        rows = rows_of(root, slug, "opening_balances.tsv")
        kept = [r for r in rows if not (r["year"] == str(year + 1)
                                        and r["source"] == "year_close")]
        removed = len(rows) - len(kept)
        if not removed:
            raise DataError(f"{year} ili bağlı deyil")
        save_rows(root, slug, "opening_balances.tsv", kept)
        tx.log("", f"reopen {year}", f"{removed} sətir", "silindi")
    return f"{year}"


def set_writeoff(root: Path, slug: str, p: dict) -> str:
    """Record (or withdraw) the decision to write an asset off under 500/5%."""
    """Record (or withdraw) the 114.8 write-off for one asset or for many.

    Many matters more than it looks. Every transaction backs the whole client
    folder up, then reloads and recomputes every open year (§8.1) -- correct
    for one decision, absurd forty times over when a workshop's worth of
    tooling crosses the threshold in the same year. Forty backups, forty
    recomputes, forty lines of changelog for what the accountant did as a
    single act.

    So the decision is one transaction whatever its size: all the assets land
    together or none of them do. The changelog still gets a line per asset --
    the grouping is a convenience for the person, not a reason to record less
    about what happened.
    """
    year = int(p["year"])
    ids = p.get("asset_ids")
    if ids is None:
        ids = [p["asset_id"]]
    elif isinstance(ids, str):
        ids = [i for i in (s.strip() for s in ids.split(",")) if i]
    ids = [str(i) for i in ids]
    if not ids:
        raise DataError("silinmə üçün ƏV seçilməyib")

    with transaction(root, slug, "writeoff.set") as tx:
        guard_open_year(root, slug, year)
        known = {r["asset_id"] for r in rows_of(root, slug, "assets.tsv")}
        missing = [i for i in ids if i not in known]
        if missing:
            raise DataError("ƏV tapılmadı: " + ", ".join(missing))
        rows = rows_of(root, slug, "writeoffs.tsv")
        target = set(ids)
        rows = [r for r in rows
                if not (r["asset_id"] in target and r["year"] == str(year))]
        if p.get("enabled"):
            reason = str(p.get("reason", "")).strip() or \
                "VM m.114 — 500/5% həddi, birdəfəlik silinmə"
            for aid in ids:
                rows.append({"year": str(year), "asset_id": aid, "reason": reason})
                tx.log(aid, f"writeoff {year}", "", reason)
        else:
            for aid in ids:
                tx.log(aid, f"writeoff {year}", "var", "silindi")
        save_rows(root, slug, "writeoffs.tsv", rows)
    return ", ".join(ids)


def set_election(root: Path, slug: str, p: dict) -> str:
    """Set the depreciation rate for a category, or for one asset."""
    year = int(p["year"])
    category = category_of(p.get("category"))
    aid = str(p.get("asset_id", "")).strip()
    with transaction(root, slug, "election.set") as tx:
        guard_open_year(root, slug, year)
        rows = rows_of(root, slug, "rate_elections.tsv")
        rows = [r for r in rows if not (
            r["year"] == str(year) and r["category"] == category
            and r.get("asset_id", "") == aid)]
        value = str(p.get("applied_rate", "")).strip()
        target = aid or category
        if value == "":
            tx.log(aid, f"rate {category} {year}", "var", "silindi")
        else:
            rate = D(value.replace(",", ".").rstrip("%"))
            if rate > 1:
                rate = rate / 100          # accept both 25 and 0.25
            rows.append({"year": str(year), "category": category,
                         "applied_rate": f"{rate:.4f}".rstrip("0").rstrip("."),
                         "asset_id": aid})
            tx.log(aid, f"rate {category} {year}", "", f"{rate:.2%}")
        _ = target
        save_rows(root, slug, "rate_elections.tsv", rows)
    return aid or category


def _pct(value: D) -> str:
    """A rate as a percentage, keeping the digits it actually has.

    25% x 1.5 is 37.5%, and rounding that to "38%" in a message is not a
    cosmetic loss: 38% is above the ceiling it is describing.
    """
    return _plain(value * 100) + "%"


def _ceiling(year: int, category: str, coefficient: D) -> D | None:
    st = rates.statutory(year, category)
    if st.max_rate is None:
        return None
    return min(st.max_rate * coefficient, D("1"))


def set_status(root: Path, slug: str, p: dict) -> str:
    year = int(p["year"])
    status = str(p.get("status", "")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")
    use_coefficient = bool(p.get("use_coefficient"))
    coefficient = (rates.multiplier(year, status).coefficient
                   if use_coefficient else D("1"))

    # The lock comes first: a closed year is refused because it is closed, and
    # saying anything else about it -- a rate above its ceiling, say -- names
    # a reason the user could act on when the real one is that the return has
    # been filed.
    guard_open_year(root, slug, year)

    # Lowering the status -- or waiving the coefficient -- lowers the CEILING,
    # and a rate already on file can end up above it. The transaction would
    # catch that anyway and roll back, but the message it produced talked
    # about a depreciation rate the user had not touched, on a form about
    # status. Name the rate that is in the way and where to change it.
    blocked = []
    for e in load_client(root, slug).elections:
        if e.year != year:
            continue
        ceiling = _ceiling(year, e.category, coefficient)
        if ceiling is not None and e.applied_rate > ceiling:
            who = f" ({e.asset_id})" if e.asset_id else ""
            blocked.append(f"{e.category}{who} — {_pct(e.applied_rate)} > "
                           f"{_pct(ceiling)}")
    if blocked:
        raise DataError(
            f"{year}: status dəyişdirilə bilməz, çünki seçilmiş amortizasiya "
            f"dərəcəsi yeni yuxarı həddi aşır — " + "; ".join(blocked) + ". "
            f"Əvvəlcə həmin dərəcəni azaldın (kateqoriya sətrində «dərəcəni "
            f"dəyiş», ƏV kartında «Fərdi dərəcə»), sonra statusu dəyişin."
        )

    with transaction(root, slug, "status.set") as tx:
        guard_open_year(root, slug, year)
        rows = rows_of(root, slug, "taxpayer_status.tsv")
        use = "" if use_coefficient else "0"
        old = next((r for r in rows if r["year"] == str(year)), None)
        if old:
            if old["status"] != status:
                tx.log("", f"status {year}", old["status"], status)
            if old.get("use_coefficient", "") != use:
                tx.log("", f"əmsal {year}",
                       "istifadə" if old.get("use_coefficient", "") != "0" else "imtina",
                       "istifadə" if use != "0" else "imtina")
            old["status"] = status
            old["basis"] = str(p.get("basis", old.get("basis", ""))).strip()
            old["use_coefficient"] = use
        else:
            rows.append({"year": str(year), "status": status,
                         "basis": str(p.get("basis", "")).strip(),
                         "use_coefficient": use})
            tx.log("", f"status {year}", "", status)
        save_rows(root, slug, "taxpayer_status.tsv", rows)

        # Applying the coefficient stays a decision, never a consequence of
        # typing a status (§5.2) -- the engine has no business doubling a
        # client's depreciation on its own. What moved is WHERE the decision
        # is offered: next to the fact that creates the right, instead of on a
        # separate screen the user has to know exists. That separate screen is
        # exactly what got missed -- "I set kiçik and the 1.5 did not apply".
        # Nothing is ticked by default, so an unanswered form still elects
        # nothing.
        #
        # Only CATEGORY elections are written here. A rate chosen for a single
        # asset is more specific and keeps winning (§5.2), which is how "all
        # the cars at 1.5, except this one" stays expressible.
        chosen = p.get("apply_coefficient_to") or []
        if isinstance(chosen, str):
            chosen = [c for c in chosen.split(",") if c.strip()]
        if chosen and coefficient <= D("1"):
            raise DataError(
                f"{rates.STATUS_NAMES[status]} üçün əmsal yoxdur (×1) — "
                f"tətbiq ediləcək bir şey yoxdur"
            )
        if chosen:
            elections = rows_of(root, slug, "rate_elections.tsv")
            for code in chosen:
                code = category_of(code)
                ceiling = _ceiling(year, code, coefficient)
                if ceiling is None:
                    continue
                elections = [r for r in elections if not (
                    r["year"] == str(year) and r["category"] == code
                    and not r.get("asset_id", ""))]
                elections.append({"year": str(year), "category": code,
                                  "applied_rate": _plain(ceiling), "asset_id": ""})
                tx.log("", f"rate {code} {year}", "", _pct(ceiling))
            save_rows(root, slug, "rate_elections.tsv", elections)
    return status


def set_rate_row(root: Path, slug: str, p: dict) -> str:
    """Add a row to the installation-wide rates.tsv.

    Not per client: the tax code is the same for everyone (§5.1). Rolls back
    if the new table stops any open year from computing.

    APPEND ONLY through the interface. §5.1 keeps in-place correction legal --
    a rate we transcribed wrong makes every year computed from it wrong, so
    the fix has to reach backwards -- but that is the owner's act, carried by
    an engine release or by editing rates.tsv directly. It must not be a
    button, because the one form that did both wrote a year the user never
    typed: the field arrived pre-filled with the engine's placeholder, and
    saving without touching it silently claimed the past as the owner's.
    `allow_past` is the deliberate override, not offered in the UI.
    """
    year = int(p["effective_year"])
    cat = category_of(p.get("category"))
    path = root / "rates.tsv"

    if not p.get("allow_past") and not p.get("remove"):
        years = rates.rate_years(cat)
        newest = max(years) if years else None
        if newest is not None and year <= newest:
            raise DataError(
                f"«{rates.CATEGORY_BY_CODE[cat].name_az}» üzrə {newest}-ci ildən "
                f"qüvvədə olan norma var. Yeni norma {newest + 1} və ya sonrakı "
                f"ildən qüvvəyə minə bilər — keçmiş illər təqdim edilmiş "
                f"bəyannamələrdir və dəyişdirilmir."
            )
        # A row identical to what already applies is not a change; it only
        # turns "proqramdan" into "əl ilə yazılıb" and pretends someone
        # decided something. Refuse it instead of storing noise.
        if newest is not None:
            cur = rates.statutory(year, cat)
            new_max = _rate_or_blank(p.get("max_rate"))
            new_lim = _rate_or_blank(p.get("repair_limit"))
            same_max = new_max == "" or (cur.max_rate is not None
                                         and D(new_max) == cur.max_rate)
            same_lim = new_lim == "" or (cur.repair_limit is not None
                                         and D(new_lim) == cur.repair_limit)
            if same_max and same_lim:
                raise DataError(
                    "Dəyişiklik yoxdur: göstərilən dəyərlər hazırda qüvvədə "
                    "olan norma ilə eynidir."
                )

    before = path.read_bytes() if path.exists() else None
    rows = [{h: r.get(h, "") for h in rates.RATES_HEADER}
            for r in read_tsv(path)]
    rows = [r for r in rows
            if not (r["effective_year"] == str(year) and r["category"] == cat)]
    if not p.get("remove"):
        rows.append({
            "effective_year": str(year), "category": cat,
            "max_rate": _rate_or_blank(p.get("max_rate")),
            "repair_limit": _rate_or_blank(p.get("repair_limit")),
            "note": str(p.get("note", "")).strip(),
        })
    write_tsv(path, rates.RATES_HEADER,
              [[r.get(h, "") for h in rates.RATES_HEADER] for r in rows])
    try:
        _recompute_everything(root)
    except BaseException:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        rates.refresh(root)
        raise
    return f"{cat} {year}"


def set_coefficient_row(root: Path, slug: str, p: dict) -> str:
    """Append-only, for the same reason as set_rate_row above."""
    year = int(p["effective_year"])
    status = str(p.get("status", "")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")
    path = root / "coefficients.tsv"

    if not p.get("allow_past") and not p.get("remove"):
        years = rates.coef_years(status)
        newest = max(years) if years else None
        if newest is not None and year <= newest:
            raise DataError(
                f"«{rates.STATUS_NAMES[status]}» üzrə {newest}-ci ildən qüvvədə "
                f"olan əmsal var. Yenisi {newest + 1} və ya sonrakı ildən "
                f"qüvvəyə minə bilər."
            )
        if newest is not None and str(p.get("coefficient", "")).strip():
            if D(str(p["coefficient"]).replace(",", ".")) == \
                    rates.multiplier(year, status).coefficient:
                raise DataError("Dəyişiklik yoxdur: əmsal hazırkı ilə eynidir.")

    before = path.read_bytes() if path.exists() else None
    rows = [{h: r.get(h, "") for h in rates.COEFF_HEADER} for r in read_tsv(path)]
    rows = [r for r in rows
            if not (r["effective_year"] == str(year) and r["status"] == status)]
    if not p.get("remove"):
        rows.append({"effective_year": str(year), "status": status,
                     "coefficient": str(p.get("coefficient", "")).strip(),
                     "note": str(p.get("note", "")).strip()})
    write_tsv(path, rates.COEFF_HEADER,
              [[r.get(h, "") for h in rates.COEFF_HEADER] for r in rows])
    try:
        _recompute_everything(root)
    except BaseException:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        rates.refresh(root)
        raise
    return f"{status} {year}"


def _plain(value: D) -> str:
    """Decimal as a plain string, without exponent and without eating digits.

    `f"{v:f}".rstrip("0")` looks like the obvious way to drop trailing zeros
    and is a trap: "800.000000" loses its own zeros too and is stored as "8".
    Only strip when there is a fractional part to strip.
    """
    s = f"{value:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def set_parameter_row(root: Path, slug: str, p: dict) -> str:
    """Append a figure of the law (the write-off threshold, and whatever a
    future amendment adds) to the installation-wide parameters.tsv.

    Same append-only rule as the rates: the past is where filed returns live.
    """
    year = int(p["effective_year"])
    key = str(p.get("key", "")).strip()
    if key not in rates.PARAM_DEFS:
        raise DataError(f"Naməlum parametr: {key!r}")
    raw = str(p.get("value", "")).strip().replace(",", ".").rstrip("%")
    if raw == "":
        raise DataError("Dəyər boş ola bilməz")
    value = D(raw)
    kind = rates.PARAM_DEFS[key][2]
    if kind == "pct":
        if value > 1:
            value = value / 100        # accept both 5 and 0.05
        if not (0 <= value <= 1):
            raise DataError("Faiz 0 ilə 100 arasında olmalıdır")
    elif value < 0:
        raise DataError("Məbləğ mənfi ola bilməz")

    path = root / "parameters.tsv"
    if not p.get("allow_past") and not p.get("remove"):
        years = rates.param_years(key)
        newest = max(years) if years else None
        if newest is not None and year <= newest:
            raise DataError(
                f"«{rates.PARAM_DEFS[key][0]}» üzrə {newest}-ci ildən qüvvədə "
                f"olan dəyər var. Yenisi {newest + 1} və ya sonrakı ildən "
                f"qüvvəyə minə bilər."
            )
        if newest is not None and value == rates.parameter(year, key):
            raise DataError("Dəyişiklik yoxdur: dəyər hazırkı ilə eynidir.")

    before = path.read_bytes() if path.exists() else None
    rows = [{h: r.get(h, "") for h in rates.PARAM_HEADER} for r in read_tsv(path)]
    rows = [r for r in rows
            if not (r["effective_year"] == str(year) and r["key"] == key)]
    if not p.get("remove"):
        rows.append({"effective_year": str(year), "key": key,
                     "value": _plain(value),
                     "note": str(p.get("note", "")).strip()})
    write_tsv(path, rates.PARAM_HEADER,
              [[r.get(h, "") for h in rates.PARAM_HEADER] for r in rows])
    try:
        _recompute_everything(root)
    except BaseException:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        rates.refresh(root)
        raise
    return f"{key} {year}"


def _rate_or_blank(value: Any) -> str:
    v = str(value or "").strip().replace(",", ".").rstrip("%")
    if v == "":
        return ""
    d = D(v)
    if d > 1:
        d = d / 100                    # accept both 5 and 0.05
    if d < 0 or d > 1:
        raise DataError(f"dərəcə 0 və 1 arasında olmalıdır — {value!r}")
    return f"{d:.4f}".rstrip("0").rstrip(".")


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


class _DryRun(Exception):
    """Raised to force the transaction to roll back after a validation pass."""


IMPORT_FIELDS = ("inv_no", "name", "category", "in_date", "cost",
                 "opening_residual", "counterparty", "note")

# Header names seen in the wild: the source workbook, 1C exports, and the
# obvious Russian/English equivalents. Matching is case- and space-insensitive.
IMPORT_ALIASES = {
    "inv_no": ["inv", "inv.№", "inv №", "inv no", "invno", "inventar",
               "inventar nömrəsi", "nömrə", "nomre", "№", "kod nömrə",
               "инв", "инв.№", "инв №", "инвентарный номер", "номер"],
    "name": ["ad", "adı", "adi", "name", "наименование", "название", "ос"],
    "category": ["kod", "kateqoriya", "категория", "код", "group", "qrup"],
    "in_date": ["alış tarixi", "alis tarixi", "tarix", "дата", "дата приобретения",
                "date", "in_date"],
    "cost": ["ilkin dəyər", "ilkin deyer", "первоначальная стоимость",
             "первоначальная", "cost", "dəyər", "alış qiyməti", "qiymət",
             "стоимость", "цена"],
    "opening_residual": ["qalıq dəyər", "qaliq deyer", "qalıq", "остаточная стоимость",
                         "остаток", "residual", "qalıq (il əvvəli)"],
    "counterparty": ["kontragent", "контрагент", "təchizatçı", "поставщик", "supplier"],
    "note": ["qeyd", "примечание", "note", "комментарий"],
}


def _fold(text: object) -> str:
    """Casefold a header for comparison, Azerbaijani-safe.

    `"İnv.№".lower()` is NOT `"inv.№"`: the dotted capital İ lowercases to an
    `i` followed by a combining dot above, so a plain comparison misses every
    header that starts with it. The dotted/dotless pair İ i I ı is folded to a
    single `i` and combining marks are dropped. `ə ç ş ğ ö ü` are letters in
    their own right and survive untouched.
    """
    s = str(text or "")
    for ch in "İIı":
        s = s.replace(ch, "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


# People type headers without the Azerbaijani letters all the time -- "Deyer"
# for "Dəyər", "Qaliq" for "Qalıq". A second, blunter fold lets those match
# too. Used only for comparing headers, never for storing anything.
_ASCII = str.maketrans({"ə": "e", "ç": "c", "ş": "s", "ğ": "g", "ö": "o", "ü": "u"})


def _fold2(text: object) -> str:
    return _fold(text).translate(_ASCII)


def guess_columns(header: list[str]) -> dict[str, int]:
    """Best-effort mapping of source columns to our fields. The user corrects
    it in the UI; guessing only removes the boring part."""
    norm = [_fold(h) for h in header]
    norm2 = [_fold2(h) for h in header]
    out: dict[str, int] = {}
    for field, aliases in IMPORT_ALIASES.items():
        folded = {_fold(a) for a in aliases} | {_fold2(a) for a in aliases}
        for i, (h, h2) in enumerate(zip(norm, norm2)):
            if i in out.values() or not h:
                continue
            if any(x in folded or any(a and (x.startswith(a) or a in x) for a in folded)
                   for x in (h, h2)):
                out[field] = i
                break
    return out


def import_assets(root: Path, slug: str, p: dict) -> Any:
    """Bulk import. `dry_run` validates through the exact same path and then
    rolls back, so the preview cannot disagree with the real import."""
    rows = p.get("rows") or []
    year = int(p.get("opening_year") or 0)
    dry = bool(p.get("dry_run"))
    report: dict[str, Any] = {"created": 0, "errors": [], "rows": []}

    try:
        with transaction(root, slug, "asset.import") as tx:
            assets = rows_of(root, slug, "assets.tsv")
            ob = rows_of(root, slug, "opening_balances.tsv")
            seen_inv = {r["inv_no"] for r in assets if r["inv_no"]}

            for n, raw in enumerate(rows, start=1):
                try:
                    inv = str(raw.get("inv_no", "")).strip()
                    name = str(raw.get("name", "")).strip()
                    if not name and not inv:
                        continue                       # blank line, skip quietly
                    if not name:
                        raise DataError("Adı boş")
                    if inv and inv in seen_inv:
                        raise DataError(f"inv_no {inv!r} təkrarlanır")
                    category = category_of(raw.get("category"))
                    if not inv:
                        inv = suggest_inv_no(assets, category)
                        auto_inv = True
                    else:
                        auto_inv = False
                    residual = str(raw.get("opening_residual", "")).strip()
                    cost_raw = str(raw.get("cost", "")).strip()
                    in_date = iso_date(raw.get("in_date"), "Alış tarixi",
                                       required=False)
                    mode = "carried" if residual else "new"
                    if mode == "new" and not cost_raw:
                        raise DataError("nə ilkin dəyər, nə qalıq dəyər var")
                    cost = dec(cost_raw or "0", "İlkin dəyər")
                    if mode == "new" and not in_date:
                        raise DataError("Alış tarixi tələb olunur")

                    aid = next_asset_id(assets)
                    assets.append({
                        "asset_id": aid, "inv_no": inv, "name": name,
                        "category": category, "in_date": in_date, "cost": cost,
                        "counterparty": str(raw.get("counterparty", "")).strip(),
                        "useful_life": "", "is_legacy_pool": "",
                        "note": str(raw.get("note", "")).strip(),
                    })
                    if inv:
                        seen_inv.add(inv)
                    residual_norm = ""
                    if residual:
                        if not year:
                            raise DataError("qalıq dəyər üçün il göstərilməyib")
                        residual_norm = dec(residual, "Qalıq dəyər")
                        ob.append({
                            "year": str(year), "asset_id": aid, "category": category,
                            "residual": residual_norm,
                            "source": "onboarding", "engine_version": "",
                            "closed_at": "",
                        })
                    report["created"] += 1
                    # Report the NORMALISED numbers: the preview must show the
                    # value that will actually be stored, not the raw cell.
                    report["rows"].append({"line": n, "asset_id": aid, "inv_no": inv,
                                           "auto_inv": auto_inv,
                                           "name": name, "category": category,
                                           "cost": cost, "residual": residual_norm,
                                           "in_date": in_date, "mode": mode,
                                           "ok": True})
                except DataError as e:
                    report["errors"].append({"line": n, "message": str(e)})
                    report["rows"].append({"line": n, "inv_no": raw.get("inv_no", ""),
                                           "name": raw.get("name", ""), "ok": False,
                                           "message": str(e)})

            if report["errors"]:
                raise DataError(
                    f"{len(report['errors'])} sətirdə xəta var — heç nə yazılmadı. "
                    f"Import ya bütövlükdə keçir, ya da heç keçmir."
                )
            if year:
                guard_open_year(root, slug, year)
            save_rows(root, slug, "assets.tsv", assets)
            save_rows(root, slug, "opening_balances.tsv", ob)
            tx.log("", "import", "", f"{report['created']} ƏV")
            if dry:
                raise _DryRun
    except _DryRun:
        report["dry_run"] = True
    except DataError:
        if not dry:
            raise
        report["dry_run"] = True
    return report


ACTIONS = {
    "asset.import": import_assets,
    "rate.set": set_rate_row,
    "coefficient.set": set_coefficient_row,
    "parameter.set": set_parameter_row,
    "asset.create": create_asset,
    "asset.update": update_asset,
    "asset.delete": delete_asset,
    "opening.set": set_opening,
    "disposal.set": set_disposal,
    "repair.add": add_repair,
    "addition.add": add_addition,
    "addition.remove": remove_addition,
    "repair.remove": remove_repair,
    "writeoff.set": set_writeoff,
    "election.set": set_election,
    "status.set": set_status,
    "client.create": create_client,
    "client.update": update_client,
    "client.import": import_client,
    "year.close": close_year,
    "year.reopen": reopen_year,
}
