#!/usr/bin/env python3
"""Əsas Vəsaitlər — CLI entry point.

    python ev.py                          start the local UI (default)
    python ev.py calc <client> <year>     print the year report to the console
    python ev.py export <client> <year>   write an .xlsx next to the client folder
    python ev.py close <client> <year>    close the year -> opening balances for year+1
    python ev.py verify <client>          recompute closed years, diff against stored
    python ev.py test                     run the engine's control examples
    python ev.py golden                   check demo-avto's output against tests/golden/
    python ev.py golden --update          regenerate tests/golden/ after a deliberate change
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.calc import MONTHS_AZ, CalcError, compute_year  # noqa: E402
from engine.excel import build_workbook  # noqa: E402
from engine.rates import ENGINE_VERSION  # noqa: E402
from engine.storage import (  # noqa: E402
    OPENING_HEADER, DataError, append_tsv, list_clients, load_client,
)


def cmd_calc(slug: str, year: int) -> None:
    r = compute_year(load_client(ROOT, slug), year)
    w = 15
    print(f"\n  {r.client_name} · VÖEN {r.voen} · {r.year}"
          f"{'  [İL BAĞLIDIR]' if r.is_closed else ''}")
    print(f"  {r.status_name} · engine {r.engine_version} · format v{r.format_version}\n")
    for cat in r.categories:
        ri = cat.rate
        if ri.method == "duz":
            # A straight-line category has no ceiling to state and no rate to
            # change -- the schedule comes from a term, per card. Printing the
            # generic "norm x coefficient = ceiling" line here would show
            # "0% x 1 = 0% hədd" (nothing has a category-wide rate) and flag
            # every card as "fərdi dərəcə", same bug the web table already
            # avoids (table.js, §5.2) by asking the method first.
            law = "m.115.6-1" if cat.code == "it" else "m.114.3.6"
            print(f"  {cat.name_az}  —  düz xətt ({law}) · "
                  f"müddət hər kartda · sahibkar əmsalı tətbiq olunmur")
        else:
            # Kept out of the f-string: an expression spanning lines inside
            # one is PEP 701, i.e. 3.12+, and this file claims 3.11 as its
            # floor. Nothing said so until CI ran the 3.11 leg -- the module
            # did not even parse.
            note = ("  (fərdi dərəcələr var)" if cat.mixed_rates else
                    "  (həddən aşağı)" if ri.below_ceiling else "")
            print(f"  {cat.name_az}  —  {ri.statutory_max:.0%} × {ri.coefficient} "
                  f"= {ri.ceiling:.0%} hədd, tətbiq {ri.applied:.0%}{note}")
        print(f"    {'İnv.№':<10}{'Adı':<26}{'Qalıq(əvv)':>{w}}{'Daxil':>{w}}"
              f"{'Xaric':>{w}}{'Amort.':>{w}}{'Silinmə':>{w}}{'Qalıq(son)':>{w}}")
        for c in cat.cards:
            flag = "⚠" if c.threshold_hit else (" →" if c.disposal_type else "  ")
            print(f"  {flag}{c.inv_no:<10}{c.name[:25]:<26}"
                  f"{c.opening:>{w},.2f}{c.acquisition:>{w},.2f}{c.disposed:>{w},.2f}"
                  f"{c.depreciation:>{w},.2f}{c.writeoff:>{w},.2f}{c.closing:>{w},.2f}")
        print(f"    {'':<36}{cat.opening:>{w},.2f}{cat.acquisition:>{w},.2f}"
              f"{cat.disposed:>{w},.2f}{cat.depreciation:>{w},.2f}"
              f"{cat.writeoff:>{w},.2f}{cat.closing:>{w},.2f}\n")
    t = r.totals
    print(f"    {'C Ə M İ':<36}{t['opening']:>{w},.2f}{t['acquisition']:>{w},.2f}"
          f"{t['disposed']:>{w},.2f}{t['depreciation']:>{w},.2f}"
          f"{t['writeoff']:>{w},.2f}{t['closing']:>{w},.2f}")
    # The point of the whole run. Everything above is how these were arrived
    # at; the console used to stop before saying them, and the disposal
    # figures in particular appeared nowhere at all (§12.1).
    print("\n  BƏYANNAMƏYƏ GEDƏN MƏBLƏĞLƏR")
    for line in r.declaration:
        effect = "çıxılır" if line.effect == "deduction" else "gəlirə əlavə"
        print(f"    {line.article:<10}{line.label_az:<42}"
              f"{line.amount:>{w},.2f}  {effect}")
    print(f"    {'':<52}{'-' * w}")
    print(f"    {'Gəlirdən çıxılır':<52}{r.declaration_deducted:>{w},.2f}")
    print(f"    {'Gəlirə əlavə edilir':<52}{r.declaration_income:>{w},.2f}")
    print(f"    {'Vergi tutulan gəlirə təsir':<52}{r.declaration_net:>{w},.2f}")
    if r.disposed_cards:
        print("\n    Xaricetmə (m.114.6 — qalıq onsuz da bazadan çıxılıb):")
        for c in r.disposed_cards:
            when = c.disposal_date.isoformat() if c.disposal_date else "—"
            print(f"      {c.inv_no or c.name[:10]:<10}{c.name[:22]:<23}"
                  f"{c.disposal_type:<13}{when:<12}"
                  f"satış {c.proceeds:>11,.2f}  qalıq {c.disposed:>11,.2f}"
                  f"  fərq {c.gain_loss:>11,.2f}")

    print("\n  Aylıq amortizasiya (illik / 12):")
    for i, mm in enumerate(r.monthly):
        print(f"    {MONTHS_AZ[i]:<10}{mm:>12,.2f}", end="\n" if (i + 1) % 3 == 0 else "")
    for wmsg in r.warnings:
        print(f"  ⚠  {wmsg}")
    for q in r.open_questions:
        print(f"  ?  {q}")
    print()


def cmd_export(slug: str, year: int) -> None:
    data = load_client(ROOT, slug)
    r = compute_year(data, year)
    out = ROOT / "clients" / slug / f"{slug}-{year}-amortizasiya.xlsx"
    out.write_bytes(build_workbook(r, data.card_meta()))
    print(f"yazıldı: {out}")


def cmd_close(slug: str, year: int) -> None:
    """Write closing balances as next year's opening balances (CLAUDE.md §6)."""
    from engine.mutate import close_year
    print(close_year(ROOT, slug, {"year": year}))


def cmd_verify(slug: str) -> None:
    """Recompute every closed year and diff against the stored balances.

    The logic itself lives in engine.mutate.verify_client now -- moved,
    unchanged, so the self-update's post-update check (web/app.py, §9) calls
    the same function this command has always printed, instead of growing a
    second copy that could drift from it.
    """
    from engine.mutate import verify_client
    bad = verify_client(ROOT, slug)
    for m in bad:
        print(f"  ✗ {m['year']}→{m['year'] + 1} {m['asset_id']}: "
              f"saxlanmış {m['stored']} ≠ yenidən hesablanmış {m['recomputed']}")
    print("  ✓ bütün bağlı illər uyğundur" if not bad else f"  {len(bad)} uyğunsuzluq")


def cmd_test() -> int:
    """The control examples §5.6 asks for, as one command.

    Separate from `verify`, which checks THIS installation's closed years
    against their seals. These check the engine itself, and they run without
    any client data.
    """
    import unittest
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                                top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_golden(update: bool) -> int:
    """Check -- or, with --update, regenerate -- tests/golden/demo-avto.json.

    `test` (above) already runs this as part of the suite (tests/test_golden.py)
    when a snapshot exists; this command is the one that produces it in the
    first place, or moves it after a deliberate change. Never hand-edit the
    JSON file: it is generated output, and the only thing worth reading by
    hand is the diff `git diff` shows after this runs.
    """
    from tests.golden import DEMO_SLUG, client_snapshot, golden_path, write_golden
    if not (ROOT / "clients" / DEMO_SLUG).is_dir():
        print(f"  {DEMO_SLUG} yoxdur -- yoxlanacaq heç nə yoxdur")
        return 0
    if update:
        path = write_golden(ROOT, DEMO_SLUG)
        print(f"  yazıldı: {path}")
        print("  `git diff` ilə nəyin dəyişdiyinə baxın")
        return 0
    import json
    path = golden_path(DEMO_SLUG)
    if not path.is_file():
        print(f"  {path} yoxdur — əvvəlcə `python ev.py golden --update` işə salın")
        return 1
    saved = json.loads(path.read_text(encoding="utf-8"))
    current = client_snapshot(ROOT, DEMO_SLUG)
    if current == saved:
        print("  ✓ golden snapshot ilə üst-üstə düşür")
        return 0
    print("  ✗ golden snapshot ilə uyğunsuzluq — "
          "`python ev.py golden --update` ilə yeniləyin və diffi oxuyun")
    return 1


def _utf8_console() -> None:
    """Make the console able to print Azerbaijani before anything prints.

    Every report here is in Azerbaijani, and a Windows console starts on the
    ANSI codepage, where `ə ğ ı ş` simply do not exist. `python ev.py calc`
    from an ordinary cmd window therefore died on UnicodeEncodeError halfway
    through the first category -- not with a wrong number, but with a
    traceback where a report should be. Başlat.bat sets `chcp 65001` and
    PYTHONIOENCODING, so the UI never showed this; the CLI is reached
    without it.

    Both halves are needed: reconfiguring the stream alone writes UTF-8 bytes
    into a cp866 console and produces mojibake, and setting the codepage
    alone leaves Python encoding to the old one. `backslashreplace` is the
    last resort -- a garbled letter is a bad report, a traceback is no
    report at all, and §2.1 is about substituted numbers, not letters.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str]) -> int:
    _utf8_console()
    if not argv or argv[0] in ("serve", "ui"):
        from web.app import serve
        serve()
        return 0
    cmd = argv[0]
    try:
        if cmd == "clients":
            for s in list_clients(ROOT):
                print(" ", s)
        elif cmd == "calc":
            cmd_calc(argv[1], int(argv[2]))
        elif cmd == "export":
            cmd_export(argv[1], int(argv[2]))
        elif cmd == "close":
            cmd_close(argv[1], int(argv[2]))
        elif cmd == "verify":
            cmd_verify(argv[1])
        elif cmd == "test":
            return cmd_test()
        elif cmd == "golden":
            return cmd_golden(update="--update" in argv[1:])
        else:
            print(__doc__)
            return 2
    except (DataError, CalcError) as e:
        # §2.1 — report the failure, never substitute a plausible number.
        print(f"\n  XƏTA: {e}\n", file=sys.stderr)
        return 1
    except IndexError:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
