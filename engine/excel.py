"""Excel export. One click from the UI -> a workbook the accountant can hand over.

Values only, no formulas: the engine is the source of truth (CLAUDE.md §2).
An exported book is a snapshot, never an input.
"""

from __future__ import annotations

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from datetime import date

from .calc import MONTHS_AZ, YearResult
from .rates import CATEGORIES, statutory

MONEY = "#,##0.00"
# Fractional digits only when the rate has them: 25% stays "25%", while the
# small-entrepreneur ceiling 25% x 1.5 prints as "37.5%" instead of a "38%"
# that is above the ceiling it is reporting.
PCT = "0.##%"

HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
SUB_FILL = PatternFill("solid", fgColor="E8EDF3")
TOTAL_FILL = PatternFill("solid", fgColor="D6DEE8")
WARN_FILL = PatternFill("solid", fgColor="FFF3CD")   # trips the threshold now
NEXT_FILL = PatternFill("solid", fgColor="EAF2FB")   # will trip it next year
THIN = Side(style="thin", color="B8C4D4")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _f(x: Decimal) -> float:
    return float(x)


def _header(ws, row: int, labels: list[str]) -> None:
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row, i, label)
        c.fill, c.font, c.border = HEAD_FILL, HEAD_FONT, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _sheet_declaration(wb: Workbook, r: YearResult) -> None:
    """The figures that leave this program for the profit return (§12.1).

    The first sheet in the book on purpose: it is the answer, and every sheet
    after it is the working behind one of these five lines. The list itself is
    built in the engine, so this sheet, the console and the web report cannot
    come to disagree about what the program's output actually is.
    """
    ws = wb.create_sheet("Bəyannamə")
    ws["A1"] = f"{r.client_name} — VÖEN {r.voen}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"{r.year} ili · mənfəət vergisi bəyannaməsinə köçürülən "
                f"məbləğlər · engine {r.engine_version} · "
                f"format v{r.format_version}")
    ws["A2"].font = Font(size=9, color="5A6B80")

    _header(ws, 4, ["Maddə", "Nə", "Məbləğ", "Təsir"])
    row = 5
    for ln in r.declaration:
        vals = [ln.article, ln.label_az, _f(ln.amount),
                "gəlirə əlavə edilir" if ln.effect == "income"
                else "gəlirdən çıxılır"]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row, i, v)
            c.border = BORDER
            if i == 3:
                c.number_format = MONEY
        row += 1

    row += 1
    for label, value in (("Gəlirdən çıxılır — cəmi", r.declaration_deducted),
                         ("Gəlirə əlavə edilir — cəmi", r.declaration_income),
                         ("Vergi tutulan gəlirə təsir", r.declaration_net)):
        ws.cell(row, 2, label).font = Font(bold=True)
        c = ws.cell(row, 3, _f(value))
        c.number_format, c.fill, c.font = MONEY, TOTAL_FILL, Font(bold=True)
        row += 1

    if r.disposed_cards:
        row += 2
        ws.cell(row, 1, "Təqdim edilmə — m.114.7 / m.114.9 üzrə fərq") \
          .font = Font(bold=True, size=11)
        row += 1
        _header(ws, row, ["İnv.№", "Adı", "Tarix", "Növ", "Satış məbləği",
                          "Qalıq dəyər", "Fərq"])
        row += 1
        for c in r.disposed_cards:
            vals = [c.inv_no, c.name,
                    c.disposal_date.isoformat() if c.disposal_date else "",
                    c.disposal_type, _f(c.proceeds), _f(c.disposed),
                    _f(c.gain_loss)]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row, i, v)
                cell.border = BORDER
                if i >= 5:
                    cell.number_format = MONEY
            row += 1
        ws.cell(row + 1, 1,
                "Fərq amortizasiyaya daxil deyil — bəyannamədə ayrıca "
                "sətirlərdir. Qalıq dəyərin özü m.114.6-ya görə onsuz da "
                "amortizasiya bazasından çıxılıb.") \
          .font = Font(italic=True, size=9, color="5A6B80")

    ws.freeze_panes = "A5"
    _widths(ws, [14, 34, 16, 22, 16, 16, 16])


def _sheet_summary(wb: Workbook, r: YearResult) -> None:
    ws = wb.create_sheet("Xülasə")
    ws["A1"] = f"{r.client_name} — VÖEN {r.voen}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"{r.year} ili · {r.status_name} · "
                f"engine {r.engine_version} · format v{r.format_version}")
    ws["A2"].font = Font(size=9, color="5A6B80")

    _header(ws, 4, ["Kateqoriya", "Dərəcə", "Qalıq (il əvvəli)", "Daxilolma",
                    "Kapital. təmir", "Xaricetmə", "Amortizasiya",
                    "Silinmə (500/5%)", "Qalıq (il sonu)"])
    row = 5
    for cat in r.categories:
        # A straight-line category states its term, not a percentage: the
        # charge is the base divided by the years left, so a per-cent figure
        # in this column would be one nobody can multiply back. `qma-m` has
        # not even that -- the term is on each card.
        if cat.rate.method == "duz":
            rate_cell = ("FİM üzrə" if cat.rate.per_card
                         else f"{cat.rate.term_years} il")
        else:
            rate_cell = _f(cat.rate.applied)
        vals = [cat.name_az, rate_cell, _f(cat.opening), _f(cat.acquisition),
                _f(cat.repair_capitalized), _f(cat.disposed), _f(cat.depreciation),
                _f(cat.writeoff), _f(cat.closing)]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row, i, v)
            c.border = BORDER
            if i == 2:
                if isinstance(v, str):
                    c.alignment = Alignment(horizontal="right")
                else:
                    c.number_format = PCT
            elif i > 2:
                c.number_format = MONEY
        row += 1

    t = r.totals
    vals = ["C Ə M İ", None, _f(t["opening"]), _f(t["acquisition"]),
            _f(t["repair_capitalized"]), _f(t["disposed"]), _f(t["depreciation"]),
            _f(t["writeoff"]), _f(t["closing"])]
    for i, v in enumerate(vals, start=1):
        c = ws.cell(row, i, v)
        c.fill, c.font, c.border = TOTAL_FILL, Font(bold=True), BORDER
        if i > 2:
            c.number_format = MONEY
    ws.freeze_panes = "A5"
    _widths(ws, [34, 10, 18, 16, 16, 16, 16, 18, 18])

    # The disposal difference used to be repeated here. It belongs to the
    # return rather than to the movement of the categories, so it lives on the
    # «Bəyannamə» sheet now, next to the other four figures that go with it.

    row += 3
    ws.cell(row, 1, "Dərəcənin hesablanması").font = Font(bold=True, size=11)
    row += 1
    _header(ws, row, ["Kateqoriya", "Norma (maks)", "Əmsal", "Hədd",
                      "Tətbiq olunan"])
    row += 1
    for cat in r.categories:
        ri = cat.rate
        if ri.method == "duz":
            # Norm x factor = ceiling does not describe this category at all.
            # Saying so is the only honest row: the coefficient is not merely
            # unused here, art. 114.3-2 does not reach a QMA.
            vals = [cat.name_az,
                    "FİM üzrə" if ri.per_card else f"1/{ri.term_years}",
                    "tətbiq olunmur", "düz xətt (m.114.3.6)",
                    "müddət üzrə" if ri.per_card else f"{ri.term_years} il"]
            for i, v in enumerate(vals, start=1):
                c = ws.cell(row, i, v)
                c.border = BORDER
                if i > 1:
                    c.alignment = Alignment(horizontal="right")
            row += 1
            continue
        vals = [cat.name_az, _f(ri.statutory_max), _f(ri.coefficient),
                _f(ri.ceiling), _f(ri.applied)]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row, i, v)
            c.border = BORDER
            if i in (2, 4, 5):
                c.number_format = PCT
            if i == 5 and ri.below_ceiling:
                c.fill = WARN_FILL
        row += 1


def _sheet_cards(wb: Workbook, r: YearResult,
                 meta: dict | None = None) -> None:
    """Flat card list: one row per asset, category as a COLUMN.

    Category headers used to sit as merged banner rows above each group. That
    reads well on paper and is useless in Excel -- you cannot filter or sort
    across banner rows. Flat plus an autofilter lets the accountant slice it
    any way they need.
    """
    meta = meta or {}
    ws = wb.create_sheet("Kartlar")
    # The rate is split into the norm and the factor applied to it, so that
    # "which assets carry the entrepreneur coefficient" is a column you can
    # sort and filter on rather than a figure you have to decompose in your
    # head. Norm x factor = rate, which is why the rate itself stays.
    #
    # Column formats are looked up BY NAME below. They used to be written as
    # index literals ("i >= 8 is money"), which silently means "everything
    # after this point" -- so inserting a text column ahead of the figures
    # formatted an invoice number as currency.
    # «Növ» sits next to the tax category on purpose: the two are read
    # together and confusing them is the one real risk of having both. The
    # sheet is flat with an autofilter, so "all the servers" is a filter here
    # rather than a report someone has to build (§13.1).
    head = ["⚠", "Kod", "Kateqoriya", "Növ", "İnv.№", "Adı", "Kontragent",
            "E-qaimə", "Seriya №",
            "Alış tarixi", "İlkin dəyər", "Qalıq (il əvvəli)",
            "Daxilolma", "Dəyər artımı", "Kapital. təmir", "Xaricetmə",
            "Norma (m.114.3)", "Əmsal", "Dərəcə", "Metod",
            "Amortizasiya", "Silinmə", "Qalıq (il sonu)"]
    _header(ws, 1, head)
    col = {name: i for i, name in enumerate(head, start=1)}
    pct_cols = {col["Norma (m.114.3)"], col["Dərəcə"]}
    factor_col = col["Əmsal"]
    money_cols = {col[n] for n in (
        "İlkin dəyər", "Qalıq (il əvvəli)", "Daxilolma", "Dəyər artımı",
        "Kapital. təmir", "Xaricetmə", "Amortizasiya", "Silinmə",
        "Qalıq (il sonu)")}
    row = 2
    for cat in r.categories:
        for card in cat.cards:
            flag = ("·" if card.retired
                    else "⚠" if card.threshold_hit else "◐" if card.threshold_next
                    else "→" if card.disposal_type else "")
            ri = card.rate_info or cat.rate
            norm = ri.statutory_max
            # A retired row states no rate: there is no base for one to act on.
            if card.retired or not norm:
                norm_out, factor = None, None
            elif ri.method == "duz":
                # The norm is a fraction of the term and stays; the factor
                # does not exist (no coefficient reaches a QMA) and neither
                # does an "applied rate" to multiply the base by -- that is
                # what the «Metod» column says instead.
                norm_out, factor = _f(norm), None
            else:
                norm_out, factor = _f(norm), float(card.rate / norm)
            RETIRED_AZ = {"writeoff": "500/5% silinib", "realizasiya": "satılıb",
                          "leqv": "ləğv edilib",
                          "amortizasiya": "tam amortizasiya olunub"}
            suffix = ""
            if card.is_legacy_pool:
                suffix = " (qrup qalığı)"
            elif card.retired:
                suffix = (f" ({RETIRED_AZ.get(card.retired_kind, 'balansdan çıxıb')}"
                          f"{', ' + str(card.retired_year) if card.retired_year else ''})")
            info = meta.get(card.asset_id, {})
            # Straight line: the charge is the base divided by the years
            # left, so the percentage beside it is the norm and NOT a factor
            # anyone should multiply the base by. The column says which.
            if ri.method == "duz":
                method = "düz xətt"
                if ri.term_years:
                    method += f" · {ri.term_years} il"
                if ri.remaining_years:
                    method += f" (qalan {ri.remaining_years})"
            else:
                method = "azalan qalıq"
            if card.retired:
                method = ""
            vals = [flag, card.category, cat.name_az, info.get("group", ""),
                    card.inv_no,
                    card.name + suffix,
                    info.get("counterparty", ""),
                    info.get("e_qaime", ""), info.get("serial_no", ""),
                    card.in_date.isoformat() if card.in_date else "",
                    _f(card.cost), _f(card.opening), _f(card.acquisition),
                    _f(card.addition), _f(card.repair_capitalized),
                    _f(card.disposed), norm_out, factor,
                    None if card.retired or ri.method == "duz"
                    else _f(card.rate), method,
                    _f(card.depreciation), _f(card.writeoff), _f(card.closing)]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row, i, v)
                cell.border = BORDER
                if i in pct_cols:
                    cell.number_format = PCT
                elif i == factor_col:
                    cell.number_format = "0.##\\x"
                elif i in money_cols:
                    cell.number_format = MONEY
                if card.threshold_hit:
                    cell.fill = WARN_FILL
                elif card.threshold_next:
                    cell.fill = NEXT_FILL
            row += 1
    ws.auto_filter.ref = \
        f"A1:{get_column_letter(len(head))}{max(row - 1, 1)}"
    ws.freeze_panes = "A2"
    _widths(ws, [4, 7, 26, 12, 32, 26, 16, 20, 13, 15, 17, 14, 14, 14, 14,
                 14, 8, 9, 15, 13, 17])


def _sheet_movement(wb: Workbook, r: YearResult) -> None:
    """Movement statement: cost on one side, accumulated depreciation on the
    other, meeting at the residual.

    The tax pipeline only ever needs the residual, but this is the shape an
    accountant is used to handing over and reconciling against the books.
    """
    ws = wb.create_sheet("Hərəkət")
    ws["A1"] = f"Əsas vəsaitlərin hərəkəti — {r.year}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = ("İlkin dəyər − yığılmış amortizasiya = qalıq dəyər. "
                "İlkin dəyəri məlum olmayan ƏV üçün başlanğıc qalıq dəyər "
                "ilkin dəyər kimi götürülür.")
    ws["A2"].font = Font(size=9, color="5A6B80")

    ws.merge_cells("B4:E4"); ws["B4"] = "İLKİN DƏYƏR"
    ws.merge_cells("F4:J4"); ws["F4"] = "YIĞILMIŞ AMORTİZASİYA"
    ws.merge_cells("K4:L4"); ws["K4"] = "QALIQ DƏYƏR"
    for ref in ("B4", "F4", "K4"):
        ws[ref].font = Font(bold=True, size=10, color="1F3A5F")
        ws[ref].alignment = Alignment(horizontal="center")
        ws[ref].fill = SUB_FILL

    _header(ws, 5, ["Kateqoriya",
                    "İl əvvəlinə", "Daxilolma", "Xaricetmə", "İl sonuna",
                    "İl əvvəlinə", "Hesablanmış", "Silinmə (500/5%)",
                    "Xaricetmə", "İl sonuna",
                    "İl əvvəlinə", "İl sonuna"])

    def block(label, cards, bold=False):
        g_s = sum((c.gross_start for c in cards), Decimal(0))
        g_i = sum((c.gross_in for c in cards), Decimal(0))
        g_o = sum((c.gross_out for c in cards), Decimal(0))
        a_s = sum((c.accumulated_start for c in cards), Decimal(0))
        a_c = sum((c.depreciation for c in cards), Decimal(0))
        a_w = sum((c.writeoff for c in cards), Decimal(0))
        a_o = sum((c.accumulated_out for c in cards), Decimal(0))
        o = sum((c.opening for c in cards), Decimal(0))
        cl = sum((c.closing for c in cards), Decimal(0))
        return [label, _f(g_s), _f(g_i), _f(g_o), _f(g_s + g_i - g_o),
                _f(a_s), _f(a_c), _f(a_w), _f(a_o), _f(a_s + a_c + a_w - a_o),
                _f(o), _f(cl)], bold

    row = 6
    rows = [block(cat.name_az, cat.cards) for cat in r.categories]
    rows.append(block("C Ə M İ", r.cards, bold=True))
    for vals, bold in rows:
        for i, v in enumerate(vals, start=1):
            cell = ws.cell(row, i, v)
            cell.border = BORDER
            if i > 1:
                cell.number_format = MONEY
            if bold:
                cell.fill, cell.font = TOTAL_FILL, Font(bold=True)
        row += 1
    ws.freeze_panes = "B6"
    _widths(ws, [30] + [15] * 11)


def _sheet_monthly(wb: Workbook, r: YearResult) -> None:
    """Monthly split, by category and by asset.

    A summary block per category first (that is the number usually wanted),
    then the flat per-asset table with the category as a filterable column.
    """
    ws = wb.create_sheet("Aylıq")
    ws["A1"] = f"Aylıq amortizasiya — {r.year}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = "İllik məbləğ / 12. Yuvarlaqlaşdırma qalığı dekabra yazılır."
    ws["A2"].font = Font(size=9, color="5A6B80")

    ws["A4"] = "Kateqoriya üzrə"
    ws["A4"].font = Font(bold=True, size=11)
    _header(ws, 5, ["Kateqoriya"] + MONTHS_AZ + ["C Ə M İ"])
    row = 6
    for cat in r.categories:
        ws.cell(row, 1, cat.name_az).border = BORDER
        for m in range(12):
            c = ws.cell(row, 2 + m, _f(cat.monthly[m]))
            c.number_format, c.border = MONEY, BORDER
        c = ws.cell(row, 14, _f(cat.depreciation))
        c.number_format, c.border, c.font = MONEY, BORDER, Font(bold=True)
        row += 1
    ws.cell(row, 1, "C Ə M İ").font = Font(bold=True)
    for m in range(12):
        c = ws.cell(row, 2 + m, _f(r.monthly[m]))
        c.number_format, c.fill, c.font, c.border = MONEY, TOTAL_FILL, Font(bold=True), BORDER
    c = ws.cell(row, 14, _f(r.totals["depreciation"]))
    c.number_format, c.fill, c.font, c.border = MONEY, TOTAL_FILL, Font(bold=True), BORDER

    row += 3
    ws.cell(row, 1, "ƏV üzrə").font = Font(bold=True, size=11)
    row += 1
    head_row = row
    _header(ws, row, ["Kateqoriya", "İnv.№", "Adı"] + MONTHS_AZ + ["C Ə M İ"])
    row += 1
    for cat in r.categories:
        for card in cat.cards:
            if all(m == 0 for m in card.monthly):
                continue
            for i, v in enumerate([cat.name_az, card.inv_no, card.name], start=1):
                ws.cell(row, i, v).border = BORDER
            for m in range(12):
                c = ws.cell(row, 4 + m, _f(card.monthly[m]))
                c.number_format, c.border = MONEY, BORDER
            c = ws.cell(row, 16, _f(card.depreciation))
            c.number_format, c.border, c.font = MONEY, BORDER, Font(bold=True)
            row += 1
    ws.auto_filter.ref = f"A{head_row}:P{max(row - 1, head_row)}"
    ws.freeze_panes = "D6"
    _widths(ws, [26, 12, 30] + [12] * 12 + [14])


def _sheet_repair(wb: Workbook, r: YearResult) -> None:
    cats = [c for c in r.categories if c.repair_actual != 0]
    if not cats:
        return
    ws = wb.create_sheet("Təmir m.115")
    ws["A1"] = f"Təmir xərclərinin vergi fondu — {r.year}"
    ws["A1"].font = Font(bold=True, size=12)
    _header(ws, 3, ["İnv.№", "Adı", "Faktiki təmir", "Gəlirdən çıxılan",
                    "Kapitallaşan", "Amortizasiya bazası"])
    row = 4
    for cat in cats:
        c = ws.cell(row, 1, f"{cat.name_az} — qrup limiti {cat.repair_limit:,.2f} "
                            f"(qalıq {cat.opening:,.2f})")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        c.fill, c.font = SUB_FILL, Font(bold=True)
        row += 1
        for card in cat.cards:
            if card.repair_actual == 0:
                continue
            vals = [card.inv_no, card.name, _f(card.repair_actual),
                    _f(card.repair_deductible), _f(card.repair_capitalized),
                    _f(card.base)]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row, i, v)
                cell.border = BORDER
                if i >= 3:
                    cell.number_format = MONEY
            row += 1
    t = r.totals
    vals = ["C Ə M İ", None, _f(t["repair_actual"]), _f(t["repair_deductible"]),
            _f(t["repair_capitalized"]), None]
    for i, v in enumerate(vals, start=1):
        cell = ws.cell(row, i, v)
        cell.fill, cell.font, cell.border = TOTAL_FILL, Font(bold=True), BORDER
        if i >= 3:
            cell.number_format = MONEY
    ws.freeze_panes = "A4"
    _widths(ws, [12, 32, 16, 18, 16, 20])


def _sheet_notes(wb: Workbook, r: YearResult) -> None:
    if not (r.warnings or r.open_questions or r.threshold_cards):
        return
    ws = wb.create_sheet("Qeydlər")
    row = 1
    for title, items in (("Xəbərdarlıqlar", r.warnings),
                         ("Həll olunmamış suallar", r.open_questions)):
        if not items:
            continue
        ws.cell(row, 1, title).font = Font(bold=True, size=11)
        row += 1
        for item in items:
            ws.cell(row, 1, item).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = 28
            row += 1
        row += 1
    _widths(ws, [130])


def build_workbook(r: YearResult, meta: dict | None = None) -> bytes:
    """`meta` carries the card fields the calculation has no use for --
    counterparty, e-invoice, serial -- keyed by asset_id."""
    wb = Workbook()
    wb.remove(wb.active)
    _sheet_declaration(wb, r)
    _sheet_summary(wb, r)
    _sheet_cards(wb, r, meta)
    _sheet_movement(wb, r)
    _sheet_monthly(wb, r)
    _sheet_repair(wb, r)
    _sheet_notes(wb, r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- import template -------------------------------------------------------
# Built FROM the importer's own field list, so the template and the parser
# cannot drift apart: a column that stops being recognised stops being
# offered. The first sheet is left empty on purpose -- examples live on their
# own sheet, so nothing sample-shaped can be imported by accident.

TEMPLATE_LABELS = {
    "inv_no": ("İnv.№", "Boş buraxsanız avtomatik verilir"),
    "name": ("Adı", "MƏCBURİ"),
    "category": ("Kateqoriya", "MƏCBURİ — siyahıdan seçin"),
    "in_date": ("Alış tarixi", "YYYY-MM-DD. Bu il alınıbsa məcburi"),
    "cost": ("İlkin dəyər", "Alış qiyməti, AZN"),
    "opening_residual": ("Qalıq dəyər", "İlin əvvəlinə. Doldurulubsa — "
                                        "ƏV əvvəlki illərdən gəlir"),
    "counterparty": ("Kontragent", "Satıcı / təchizatçı"),
    "e_qaime": ("E-qaimə №", "İxtiyari — alışın elektron qaiməsi"),
    "serial_no": ("Seriya №", "İxtiyari — zavod / VIN nömrəsi"),
    "group": ("Növ", "İxtiyari — müştərinin öz bölgüsü; hesabata təsir edir, "
                     "hesablamaya yox"),
    "useful_life": ("FİM (il)", "Yalnız «QMA — FİM məlum» üçün, tam illə"),
    "note": ("Qeyd", "İxtiyari"),
}

# Keyed by field, not positional. As a list of cells it silently depended on
# the order of IMPORT_FIELDS, so adding a column shifted every example one
# place to the left -- the same positional coupling §11.3 took out of the
# annual table and §11.2 out of the paste grid.
TEMPLATE_EXAMPLES = [
    {"inv_no": "NV-0001", "name": "Toyota Camry 2.5", "category": "nv",
     "in_date": "2026-02-14", "cost": "45000",
     "counterparty": "Toyota Center Baku", "e_qaime": "EQ-2026-004512",
     "serial_no": "JTNBE46K873012345", "group": "Minik avtomobilləri",
     "note": "bu il alınıb"},
    {"inv_no": "MA-0007", "name": "Kompressor", "category": "ma",
     "in_date": "2023-05-10", "cost": "12000", "opening_residual": "4800",
     "counterparty": "Aqro Texnika", "group": "Sex avadanlığı",
     "note": "əvvəlki illərdən — qalıq dəyər son bəyannamədən"},
    {"name": "Ofis mebeli", "category": "dg", "in_date": "2024-11-02",
     "cost": "3200", "opening_residual": "1900", "counterparty": "Embawood",
     "note": "inv.№ boşdur — proqram özü verəcək"},
    # A QMA, because the template is also where someone finds out the program
    # keeps them at all -- and that a known term is a column, not a category
    # note (m.114.3.6).
    {"inv_no": "QMA-0001", "name": "1C mühasibat proqramı", "category": "qma-m",
     "in_date": "2025-03-01", "cost": "6000", "useful_life": "5",
     "counterparty": "Soft Baku", "note": "FİM məlumdur — 5 il, düz xətt"},
]


def build_import_template(fields: list[str]) -> bytes:
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "ƏV"
    _header(ws, 1, [TEMPLATE_LABELS[f][0] for f in fields])
    ws.freeze_panes = "A2"
    _widths(ws, [14, 34, 16, 14, 15, 16, 26, 30])

    # QMA belongs in the dropdown; `it` does not, because the engine has no
    # schedule for it yet and a card in it stops the year computing (§12.5).
    cats = [c for c in CATEGORIES if c.code != "it"]

    ref = wb.create_sheet("Kateqoriyalar")
    _header(ref, 1, ["Kod", "Kateqoriya", "Amortizasiya norması (maks)"])
    for i, c in enumerate(cats, start=2):
        ref.cell(i, 1, c.code).border = BORDER
        ref.cell(i, 2, c.name_az).border = BORDER
        st = statutory(date.today().year, c.code)
        cell = ref.cell(i, 3, None if st.max_rate is None else float(st.max_rate))
        cell.number_format, cell.border = PCT, BORDER
    _widths(ref, [10, 34, 26])

    # a dropdown on the category column, so the code is picked, not guessed
    col = chr(ord("A") + fields.index("category"))
    dv = DataValidation(
        type="list",
        formula1=f"=Kateqoriyalar!$A$2:$A${len(cats) + 1}",
        allow_blank=False, showDropDown=False,
    )
    dv.error = "Kateqoriya siyahıdan seçilməlidir"
    dv.errorTitle = "Naməlum kateqoriya"
    ws.add_data_validation(dv)
    dv.add(f"{col}2:{col}1000")

    ex = wb.create_sheet("Nümunə")
    _header(ex, 1, [TEMPLATE_LABELS[f][0] for f in fields])
    for i, row in enumerate([[ex.get(f, "") for f in fields]
                             for ex in TEMPLATE_EXAMPLES], start=2):
        for j, v in enumerate(row[:len(fields)], start=1):
            ex.cell(i, j, v).border = BORDER
    r = len(TEMPLATE_EXAMPLES) + 3
    ex.cell(r, 1, "Sütunlar haqqında").font = Font(bold=True, size=11)
    for k, f in enumerate(fields, start=r + 1):
        label, hint = TEMPLATE_LABELS[f]
        ex.cell(k, 1, label).font = Font(bold=True)
        ex.cell(k, 2, hint)
    ex.cell(k + 2, 1,
            "Bu vərəq yalnız nümunədir — idxal birinci vərəqdən («ƏV») oxunur.")
    ex.cell(k + 2, 1).font = Font(italic=True, color="8A5B00")
    _widths(ex, [16, 46, 16, 14, 15, 16, 26, 30])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
