"""The asset card and everything that happens to one.

Acquisition, correction, deletion, opening balance, disposal, repair and
capital addition. All of them are facts about an object (§2); nothing here
stores a result."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from ..rates import CATEGORY_BY_CODE
from ..storage import DataError, check_qma

from .core import Tx, guard_open_year, rows_of, save_rows, transaction
from .groups import group_ref
from .numbering import asset_id_series, batch_count, inv_series, suggest_inv_no
from .parse import category_of, dec, iso_date

D = Decimal

MODES = ("new", "carried", "pool")


def life_of(value) -> int | None:
    """The FİM in whole years, or None when the field was left empty.

    Years, not a date: 114.3.6 spreads the cost "illər üzrə", and half a year
    is not a thing the schedule can express.
    """
    v = str(value or "").strip()
    if not v:
        return None
    try:
        n = int(v)
    except ValueError:
        raise DataError(f"İstifadə müddəti tam illə göstərilməlidir: {v!r}")
    if n < 1:
        raise DataError("İstifadə müddəti 1 ildən kiçik ola bilməz")
    return n


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
    is_qma = CATEGORY_BY_CODE[category].kind == "qma"
    life = life_of(p.get("useful_life"))
    residual = str(p.get("opening_residual", "")).strip()
    count = batch_count(p.get("say"))
    if mode == "pool" and count > 1:
        # A pool is one card standing for a group that HAS no cards. Asking for
        # 240 of them is asking for the same total 240 times over.
        raise DataError("Qrup qalığı kartsız cəmdir — say tətbiq edilmir")

    with transaction(root, slug, "asset.create") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        group_id = group_ref(root, slug, p.get("group_id"))
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
            # A QMA needs its date in every mode, `carried` included: the
            # straight line has to know which year is year zero, and a card
            # brought over from the client's last return has one just the
            # same (§5.3, the `duz` branch).
            in_date = iso_date(p.get("in_date"), "Alış tarixi",
                               required=(mode == "new" or is_qma))
            cost = dec(p.get("cost"), "İlkin dəyər",
                       allow_zero=(mode == "carried"))
            if mode == "new" and D(cost) == 0:
                raise DataError("İlkin dəyər sıfır ola bilməz")
            if mode == "carried" and not residual:
                raise DataError("Əvvəlki illərdən gələn ƏV üçün qalıq dəyər "
                                "tələb olunur")

        check_qma(category, in_date=in_date or None, useful_life=life,
                  is_legacy_pool=(mode == "pool"))

        # m.115.6-1 only reaches a repair that the lessor did NOT reimburse
        # and that was NOT offset against rent (m.115.6) -- otherwise there is
        # no deduction under this mechanism at all, not a smaller one. Asked
        # once, at creation: the fact is about the repair being capitalised,
        # not about the card's other fields, so an edit later (name, note,
        # counterparty) does not re-open it. Required rather than a silent
        # default, because a wrongly-claimed deduction is exactly the failure
        # §2.1 rules out -- and unlike most facts here, this one the engine
        # cannot check against anything else in the books.
        if category == "it" and not p.get("it_confirmed"):
            raise DataError(
                "İcarə təmiri: təsdiq tələb olunur — xərc icarədar tərəfindən "
                "ödənilməyib və icarə haqqı ilə əvəzləşdirilməyib (m.115.6, "
                "m.115.6-1). Əks halda bu maddə ilə vergidən çıxılmır."
            )

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

        # An acquisition dated inside a closed year is a fact OF that year and
        # changes its depreciation, so it is refused like any other change to
        # a filed return (§6.2). This used to be checked only for the opening
        # balance below, which left the hole open: the asset went in, the
        # closed year no longer matched its seal, and the only sign was
        # `ev.py verify` reporting a discrepancy later. Deliberately adding one
        # is still possible -- reopen the year, which is what that act is for.
        if in_date:
            guard_open_year(root, slug, int(in_date[:4]))

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
                "useful_life": "" if life is None else str(life),
                "is_legacy_pool": "1" if mode == "pool" else "",
                "note": str(p.get("note", "")).strip(),
                "e_qaime": str(p.get("e_qaime", "")).strip(),
                # A batch is N units of one purchase (§4), so they share the
                # e-invoice but NOT the serial number -- serials are what tells
                # the units apart. Filling one serial onto forty cards would
                # state something false about thirty-nine of them.
                "serial_no": (str(p.get("serial_no", "")).strip()
                              if count == 1 else ""),
                # Unlike the serial, a batch DOES share its group: forty
                # identical laptops are forty laptops.
                "group_id": group_id,
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
    life = life_of(p.get("useful_life"))
    with transaction(root, slug, "asset.update") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        row = next((r for r in assets if r["asset_id"] == aid), None)
        if row is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        category = category_of(p.get("category"))
        # Same rule create_asset already applies to a `carried` card: only a
        # QMA/`it` schedule needs a year zero (§4). Requiring it unconditionally
        # here meant a legacy asset brought in without a known purchase date
        # could never be edited again -- not even to fix its name -- because
        # the very form that was supposed to let you fill the date in later
        # also refused to save without one.
        is_qma = CATEGORY_BY_CODE[category].kind == "qma"
        new = {
            "inv_no": str(p.get("inv_no", "")).strip(),
            "name": str(p.get("name", "")).strip(),
            "category": category,
            "in_date": iso_date(p.get("in_date"), "Alış tarixi", required=is_qma),
            "cost": dec(p.get("cost"), "İlkin dəyər"),
            "useful_life": ("" if life is None else str(life)),
            "counterparty": str(p.get("counterparty", "")).strip(),
            "note": str(p.get("note", "")).strip(),
            "e_qaime": str(p.get("e_qaime", "")).strip(),
            "serial_no": str(p.get("serial_no", "")).strip(),
            "group_id": group_ref(root, slug, p.get("group_id")),
        }
        if new["inv_no"] and any(
                r["inv_no"] == new["inv_no"] and r["asset_id"] != aid for r in assets):
            raise DataError(f"inv_no {new['inv_no']!r} artıq mövcuddur")
        if not new["name"]:
            raise DataError("Adı boş ola bilməz")
        check_qma(new["category"], in_date=new["in_date"] or None,
                  useful_life=life,
                  is_legacy_pool=row.get("is_legacy_pool", "").strip()
                  in ("1", "true", "yes"))

        # Only the fields that reach the calculation are frozen by a closed
        # year. A closed year seals the RETURN, not the card: correcting a
        # misspelt name or filling in the serial of an asset bought in 2024
        # changes no figure and must stay possible. Cost, date and category do
        # change one, in the year the asset was acquired and in every year
        # after it, so they are refused for both the old and the new year --
        # moving an asset OUT of a closed year rewrites it just as much as
        # moving one in.
        # The FİM joins them: it IS the rate for a straight-line card, so
        # changing it rewrites every year the card was in.
        for field in ("cost", "in_date", "category", "useful_life"):
            if row[field] == new[field]:
                continue
            for value in (row["in_date"], new["in_date"]):
                if value:
                    guard_open_year(root, slug, int(value[:4]))

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


# Everything that points at a card. The same list delete_asset walks, which
# is the point: emptying the store must not leave behind exactly the orphans
# that deleting one card is careful to take with it.
DEPENDENT = ("opening_balances.tsv", "disposals.tsv", "repairs.tsv",
             "additions.tsv", "writeoffs.tsv", "rate_elections.tsv")


def clear_assets(root: Path, slug: str, p: dict) -> str:
    """Delete ALL cards -- "import again from scratch".

    Import appends; it has no other mode, and it should not have one, because
    "this file replaces everything" is a much bigger claim than "these rows
    are assets". So starting over is its own act, named as what it does.

    Two guards, for opposite reasons:

    * the client's name has to be typed back. Not ceremony: this is the only
      action in the program that destroys facts in bulk, and the mis-click it
      protects against is a real one -- the button sits next to ordinary
      settings;
    * a closed year refuses it outright. Its sealed balances are the evidence
      behind a filed return (§6.2), and wiping them would leave `ev.py verify`
      unable to check the very years it exists for. Reopen first, deliberately.

    What survives: the firm itself, the taxpayer status per year, the category
    rate elections, the «Növ» dictionary. None of them are facts about a card,
    and re-typing them would be re-entering work the import never touched.
    """
    from ..storage import load_client
    data = load_client(root, slug)
    typed = " ".join(str(p.get("confirm", "")).split()).casefold()
    if typed not in (data.client_name.casefold(), slug.casefold()):
        raise DataError(
            f"Təsdiq üçün müştərinin adını yazın: «{data.client_name}» "
            f"və ya «{slug}»")
    closed = sorted(data.closed_years())
    if closed:
        raise DataError(
            f"{', '.join(str(y) for y in closed)} ili bağlıdır — silinmə "
            f"qəbul edilmir. Əvvəlcə bağlanışı ləğv edin (§6.2).")

    with transaction(root, slug, "asset.clear") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        n = len(assets)
        for name in DEPENDENT:
            rows = rows_of(root, slug, name)
            # A category-wide rate election is a decision about the CATEGORY,
            # not about any card, so it stays; only the per-asset ones go.
            kept = [r for r in rows if not r.get("asset_id")]
            if len(kept) != len(rows):
                tx.log("", name, f"{len(rows) - len(kept)} sətir", "silindi")
                save_rows(root, slug, name, kept)
        tx.log("", "assets", f"{n} ƏV", "hamısı silindi")
        save_rows(root, slug, "assets.tsv", [])
    return f"{n} ƏV silindi"


def delete_assets_many(root: Path, slug: str, p: dict) -> str:
    """Delete several cards in one transaction.

    Picking them off one at a time was the only way in, and for a handful of
    mis-imported cards that means a delete_asset call each -- §8.1 backs up
    the whole folder and recomputes every open year per write, so five clicks
    became five backups and five recomputations for one bookkeeper action.
    Same reasoning as set_writeoff and group.assign taking a list (§5.3-bis,
    §13.1): the transaction is one, the changelog still gets a line per card.
    """
    ids = [str(a) for a in (p.get("asset_ids") or [])]
    if not ids:
        raise DataError("Heç bir ƏV seçilməyib")
    id_set = set(ids)
    with transaction(root, slug, "asset.delete_many") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        by_id = {r["asset_id"]: r for r in assets}
        missing = [aid for aid in ids if aid not in by_id]
        if missing:
            raise DataError(f"ƏV tapılmadı: {', '.join(missing)}")
        for name in DEPENDENT:
            rows = rows_of(root, slug, name)
            kept = [r for r in rows if r.get("asset_id") not in id_set]
            if len(kept) != len(rows):
                tx.log("", name, f"{len(rows) - len(kept)} sətir", "silindi")
                save_rows(root, slug, name, kept)
        for aid in ids:
            row = by_id[aid]
            tx.log(aid, "asset", f"{row['inv_no']} {row['name']}", "silindi")
        save_rows(root, slug, "assets.tsv",
                  [r for r in assets if r["asset_id"] not in id_set])
    return f"{len(ids)} ƏV silindi"


def delete_asset(root: Path, slug: str, p: dict) -> str:
    """Delete the asset AND everything that references it.

    Removing only the card is what left an orphaned opening balance behind
    when the files were edited by hand.
    """
    aid = str(p["asset_id"])
    with transaction(root, slug, "asset.delete") as tx:
        for name in DEPENDENT:
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


def set_repair(root: Path, slug: str, p: dict) -> str:
    """Add, correct or remove one repair-cost entry.

    Keyed by (asset_id, date), not asset_id alone -- unlike a disposal, an
    asset can legally carry several repairs in a year (or across years, see
    the `it` category, §5.1). `orig_date` names the row being replaced; a
    fresh entry has none. Correcting an amount is therefore remove-the-old
    plus add-the-new in the SAME transaction, mirroring `set_disposal` --
    not two separate actions, which would mean two backups and two
    recomputes (§8.1) for what the accountant experiences as one edit.
    """
    aid = str(p["asset_id"])
    orig = str(p.get("orig_date", "")).strip()
    with transaction(root, slug, "repair.set") as tx:
        if orig:
            guard_open_year(root, slug, int(orig[:4]))
        rows = rows_of(root, slug, "repairs.tsv")
        if orig:
            rows = [r for r in rows
                    if not (r["asset_id"] == aid and r["date"] == orig)]
        if not p.get("remove"):
            when = iso_date(p.get("date"), "Təmir tarixi")
            year = int(when[:4])
            guard_open_year(root, slug, year)
            amount = dec(p.get("amount"), "Məbləğ", allow_zero=False)
            rows.append({"year": str(year), "asset_id": aid, "date": when,
                         "amount": amount, "note": str(p.get("note", "")).strip()})
            tx.log(aid, f"repair {when}", "" if not orig else "düzəliş edildi",
                   amount)
        else:
            tx.log(aid, f"repair {orig}", "var", "silindi")
        save_rows(root, slug, "repairs.tsv", rows)
    return aid

def set_addition(root: Path, slug: str, p: dict) -> str:
    """Add, correct or remove one capital-addition entry.

    Keyed by (asset_id, date), not asset_id alone -- same reasoning as
    `set_repair`: an asset can carry several additions in a year. Correcting
    an amount is remove-the-old plus add-the-new in the SAME transaction.
    """
    aid = str(p["asset_id"])
    orig = str(p.get("orig_date", "")).strip()
    with transaction(root, slug, "addition.set") as tx:
        if orig:
            guard_open_year(root, slug, int(orig[:4]))
        rows = rows_of(root, slug, "additions.tsv")
        if orig:
            rows = [r for r in rows
                    if not (r["asset_id"] == aid and r["date"] == orig)]
        if not p.get("remove"):
            when = iso_date(p.get("date"), "Tarix")
            year = int(when[:4])
            guard_open_year(root, slug, year)
            amount = dec(p.get("amount"), "Məbləğ", allow_zero=False)
            rows.append({"year": str(year), "asset_id": aid, "date": when,
                         "amount": amount, "note": str(p.get("note", "")).strip()})
            tx.log(aid, f"addition {when}", "" if not orig else "düzəliş edildi",
                   amount)
        else:
            tx.log(aid, f"addition {orig}", "var", "silindi")
        save_rows(root, slug, "additions.tsv", rows)
    return aid

