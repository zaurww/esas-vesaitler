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

from .calc import MONTHS_AZ, YearResult

MONEY = "#,##0.00"
PCT = "0%"

HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
SUB_FILL = PatternFill("solid", fgColor="E8EDF3")
TOTAL_FILL = PatternFill("solid", fgColor="D6DEE8")
WARN_FILL = PatternFill("solid", fgColor="FFF3CD")
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
                    "Xaricetmə", "Amortizasiya", "Silinmə (500/5%)", "Qalıq (il sonu)"])
    row = 5
    for cat in r.categories:
        vals = [cat.name_az, _f(cat.rate.applied), _f(cat.opening), _f(cat.acquisition),
                _f(cat.disposed), _f(cat.depreciation), _f(cat.writeoff), _f(cat.closing)]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row, i, v)
            c.border = BORDER
            if i == 2:
                c.number_format = PCT
            elif i > 2:
                c.number_format = MONEY
        row += 1

    t = r.totals
    vals = ["C Ə M İ", None, _f(t["opening"]), _f(t["acquisition"]), _f(t["disposed"]),
            _f(t["depreciation"]), _f(t["writeoff"]), _f(t["closing"])]
    for i, v in enumerate(vals, start=1):
        c = ws.cell(row, i, v)
        c.fill, c.font, c.border = TOTAL_FILL, Font(bold=True), BORDER
        if i > 2:
            c.number_format = MONEY
    ws.freeze_panes = "A5"
    _widths(ws, [34, 10, 18, 16, 16, 16, 18, 18])

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


def _sheet_cards(wb: Workbook, r: YearResult) -> None:
    ws = wb.create_sheet("Kartlar")
    _header(ws, 1, ["⚠", "Kod", "İnv.№", "Adı", "Alış tarixi", "İlkin dəyər",
                    "Qalıq (il əvvəli)", "Daxilolma", "Xaricetmə", "Dərəcə",
                    "Amortizasiya", "Silinmə", "Qalıq (il sonu)"])
    row = 2
    for cat in r.categories:
        c = ws.cell(row, 1, cat.name_az)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=13)
        c.fill, c.font = SUB_FILL, Font(bold=True)
        row += 1
        for card in cat.cards:
            flag = "⚠" if card.threshold_hit else ("→" if card.disposal_type else "")
            vals = [flag, card.category, card.inv_no,
                    card.name + (" (legacy pool)" if card.is_legacy_pool else ""),
                    card.in_date.isoformat() if card.in_date else "",
                    _f(card.cost), _f(card.opening), _f(card.acquisition),
                    _f(card.disposed), _f(card.rate), _f(card.depreciation),
                    _f(card.writeoff), _f(card.closing)]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row, i, v)
                cell.border = BORDER
                if i == 10:
                    cell.number_format = PCT
                elif i >= 6:
                    cell.number_format = MONEY
                if card.threshold_hit:
                    cell.fill = WARN_FILL
            row += 1
    ws.freeze_panes = "A2"
    _widths(ws, [4, 7, 12, 32, 13, 15, 17, 14, 14, 9, 15, 13, 17])


def _sheet_monthly(wb: Workbook, r: YearResult) -> None:
    ws = wb.create_sheet("Aylıq")
    ws["A1"] = f"Aylıq amortizasiya — {r.year}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = "İllik məbləğ / 12. Yuvarlaqlaşdırma qalığı dekabra yazılır."
    ws["A2"].font = Font(size=9, color="5A6B80")

    _header(ws, 4, ["İnv.№", "Adı"] + MONTHS_AZ + ["C Ə M İ"])
    row = 5
    for cat in r.categories:
        for card in cat.cards:
            if all(m == 0 for m in card.monthly):
                continue
            ws.cell(row, 1, card.inv_no).border = BORDER
            ws.cell(row, 2, card.name).border = BORDER
            for m in range(12):
                c = ws.cell(row, 3 + m, _f(card.monthly[m]))
                c.number_format, c.border = MONEY, BORDER
            c = ws.cell(row, 15, _f(card.depreciation))
            c.number_format, c.border, c.font = MONEY, BORDER, Font(bold=True)
            row += 1
    ws.cell(row, 1, "C Ə M İ").font = Font(bold=True)
    for m in range(12):
        c = ws.cell(row, 3 + m, _f(r.monthly[m]))
        c.number_format, c.fill, c.font, c.border = MONEY, TOTAL_FILL, Font(bold=True), BORDER
    c = ws.cell(row, 15, _f(r.totals["depreciation"]))
    c.number_format, c.fill, c.font, c.border = MONEY, TOTAL_FILL, Font(bold=True), BORDER
    ws.freeze_panes = "C5"
    _widths(ws, [12, 30] + [12] * 12 + [14])


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


def build_workbook(r: YearResult) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    _sheet_summary(wb, r)
    _sheet_cards(wb, r)
    _sheet_monthly(wb, r)
    _sheet_repair(wb, r)
    _sheet_notes(wb, r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
