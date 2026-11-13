"""Off-site copy: a daily «⇄ Baza» archive of every client, written to a
folder OUTSIDE the installation.

The backups in backups/ (§8.3) protect against a mistake or a program bug.
They live inside the installation folder, next to clients/, so they do not
protect against the case new users actually hit: the whole folder deleted
from the desktop, or the disk gone. Only a copy elsewhere survives that.

The copy is the same archive «⇄ Baza» exports (engine.mutate.export_client),
so restoring it is the ordinary import, with its version and norms checks
(§8.2). Nothing new to learn and nothing new to trust.

Settings live in offsite.json at the installation root: this is a setting of
the installation, like the norms (§5.1), not a fact about a client, so it
does not belong in a client folder. update.PRESERVE keeps it across updates.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from engine.mutate import export_client
from engine.storage import DataError, list_clients

SETTINGS = "offsite.json"
KEEP = 30           # archives kept per client: a month of daily copies
SUFFIX = ".evbaza.zip"


def read_settings(root: Path) -> dict:
    p = root / SETTINGS
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise DataError(f"{SETTINGS} oxunmur: {e}") from None


def suggested_folder() -> str:
    """OneDrive if the machine has it -- then the copy also leaves the
    computer -- otherwise Documents, which at least survives deleting the
    program's folder."""
    base = os.environ.get("OneDrive") or str(Path.home() / "Documents")
    return str(Path(base) / "EsasVesaitler-ehtiyat")


def set_folder(root: Path, folder: str) -> str:
    """Validate and store the target. An empty value switches the copy off."""
    folder = (folder or "").strip().strip('"')
    if not folder:
        _write(root, {})
        return ""
    target = Path(folder)
    if not target.is_absolute():
        raise DataError("Tam yol yazın, məsələn C:\\Users\\...\\OneDrive\\EsasVesaitler-ehtiyat")
    target = target.resolve()
    here = root.resolve()
    # A copy inside the installation dies with it -- the one case it is for.
    if target == here or here in target.parents:
        raise DataError("Bu qovluq proqramın öz qovluğunun içindədir. Proqram "
                        "qovluğu silinsə, nüsxə də silinəcək — başqa yer seçin.")
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".yoxlama"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise DataError(f"Bu qovluğa yazmaq olmur: {e}") from None
    _write(root, {"folder": str(target)})
    return str(target)


def _write(root: Path, data: dict) -> None:
    tmp = root / (SETTINGS + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, root / SETTINGS)


def run(root: Path, today: date | None = None) -> list[str]:
    """Write today's archive for every client that has none yet; prune.

    Returns the slugs copied. Raises DataError if the target is set but
    unusable -- the caller decides how loudly to say so. A client that fails
    to export does not stop the others; its error is collected and raised at
    the end, after everyone else has been copied.
    """
    folder = read_settings(root).get("folder")
    if not folder:
        return []
    target = Path(folder)
    if not target.is_dir():
        raise DataError(f"Xarici nüsxə qovluğu tapılmadı: {folder} "
                        f"(fləş-kart çıxarılıb, ya OneDrive işləmir?)")
    stamp = (today or date.today()).strftime("%Y%m%d")
    done, errors = [], []
    for slug in list_clients(root):
        dest = target / slug
        name = f"{slug}-{stamp}{SUFFIX}"
        if (dest / name).exists():
            continue
        try:
            blob = export_client(root, slug)
            dest.mkdir(parents=True, exist_ok=True)
            tmp = dest / (name + ".tmp")
            tmp.write_bytes(blob)
            os.replace(tmp, dest / name)
            done.append(slug)
            _prune(dest, slug)
        except (OSError, DataError) as e:
            errors.append(f"{slug}: {e}")
    if errors:
        raise DataError("Xarici nüsxə: " + "; ".join(errors))
    return done


def _prune(dest: Path, slug: str) -> None:
    """Keep the newest KEEP archives of this client. Only files whose name is
    exactly ours are candidates -- anything else in the folder was put there
    by someone else and is not ours to delete (same rule as §8.3)."""
    ours = sorted(p for p in dest.glob(f"{slug}-*{SUFFIX}")
                  if p.name[len(slug) + 1:-len(SUFFIX)].isdigit())
    for p in ours[:-KEEP]:
        try:
            p.unlink()
        except OSError:
            pass   # locked by an antivirus or a sync client; next run retries


def status(root: Path) -> dict:
    """What the settings screen shows: where, and the newest copy per client."""
    try:
        folder = read_settings(root).get("folder", "")
    except DataError as e:
        return {"folder": "", "error": str(e), "suggested": suggested_folder()}
    out = {"folder": folder, "suggested": suggested_folder(), "clients": {}}
    if folder and Path(folder).is_dir():
        for slug in list_clients(root):
            files = sorted((Path(folder) / slug).glob(f"{slug}-*{SUFFIX}"))
            if files:
                d = files[-1].name[len(slug) + 1:-len(SUFFIX)]
                out["clients"][slug] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return out
