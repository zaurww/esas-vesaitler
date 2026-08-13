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
PCT = "0%"

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
        vals = [cat.name_az, _f(cat.rate.applied), _f(cat.opening), _f(cat.acquisition),
                _f(cat.repair_capitalized), _f(cat.disposed), _f(cat.depreciation),
                _f(cat.writeoff), _f(cat.closing)]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row, i, v)
            c.border = BORDER
            if i == 2:
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

    row += 3
    ws.cell(row, 1, "Dərəcənin hesablanması").font = Font(bold=True, size=11)
    row += 1
    _header(ws, row, ["Kateqoriya", "Norma (maks)", "Əmsal", "Hədd", "Tətbiq olunan"])
    row += 1
    for cat in r.categories:
        ri = cat.rate
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
                 counterparty: dict | None = None) -> None:
    """Flat card list: one row per asset, category as a COLUMN.

    Category headers used to sit as merged banner rows above each group. That
    reads well on paper and is useless in Excel -- you cannot filter or sort
    across banner rows. Flat plus an autofilter lets the accountant slice it
    any way they need.
    """
    counterparty = counterparty or {}
    ws = wb.create_sheet("Kartlar")
    _header(ws, 1, ["⚠", "Kod", "Kateqoriya", "İnv.№", "Adı", "Kontragent",
                    "Alış tarixi", "İlkin dəyər", "Qalıq (il əvvəli)",
                    "Daxilolma", "Dəyər artımı", "Kapital. təmir", "Xaricetmə",
                    "Dərəcə", "Amortizasiya", "Silinmə", "Qalıq (il sonu)"])
    row = 2
    for cat in r.categories:
        for card in cat.cards:
            flag = ("⚠" if card.threshold_hit else "◐" if card.threshold_next
                    else "→" if card.disposal_type else "")
            vals = [flag, card.category, cat.name_az, card.inv_no,
                    card.name + (" (qrup qalığı)" if card.is_legacy_pool else ""),
                    counterparty.get(card.asset_id, ""),
                    card.in_date.isoformat() if card.in_date else "",
                    _f(card.cost), _f(card.opening), _f(card.acquisition),
                    _f(card.addition), _f(card.repair_capitalized),
                    _f(card.disposed), _f(card.rate),
                    _f(card.depreciation), _f(card.writeoff), _f(card.closing)]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row, i, v)
                cell.border = BORDER
                if i == 14:
                    cell.number_format = PCT
                elif i >= 8:
                    cell.number_format = MONEY
                if card.threshold_hit:
                    cell.fill = WARN_FILL
                elif card.threshold_next:
                    cell.fill = NEXT_FILL
            row += 1
    ws.auto_filter.ref = f"A1:Q{max(row - 1, 1)}"
    ws.freeze_panes = "A2"
    _widths(ws, [4, 7, 26, 12, 32, 26, 13, 15, 17, 14, 14, 14, 14, 9, 15, 13, 17])


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


def build_workbook(r: YearResult, counterparty: dict | None = None) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    _sheet_summary(wb, r)
    _sheet_cards(wb, r, counterparty)
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
    "note": ("Qeyd", "İxtiyari"),
}

TEMPLATE_EXAMPLES = [
    ["NV-0001", "Toyota Camry 2.5", "nv", "2026-02-14", "45000", "",
     "Toyota Center Baku", "bu il alınıb"],
    ["MA-0007", "Kompressor", "ma", "2023-05-10", "12000", "4800",
     "Aqro Texnika", "əvvəlki illərdən — qalıq dəyər son bəyannamədən"],
    ["", "Ofis mebeli", "dg", "2024-11-02", "3200", "1900", "Embawood",
     "inv.№ boşdur — proqram özü verəcək"],
]


def build_import_template(fields: list[str]) -> bytes:
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "ƏV"
    _header(ws, 1, [TEMPLATE_LABELS[f][0] for f in fields])
    ws.freeze_panes = "A2"
    _widths(ws, [14, 34, 16, 14, 15, 16, 26, 30])

    cats = [c for c in CATEGORIES if not c.code.startswith("qma")]

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
    for i, row in enumerate(TEMPLATE_EXAMPLES, start=2):
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
