"""Creating a client folder and editing the firm's own details.

The folder is created complete, with every file the engine expects and headers
in place, so the store is valid from the first second rather than
materialising as features get used (§4)."""

from __future__ import annotations

import getpass
import shutil
import tomllib

from datetime import datetime, timezone
from pathlib import Path

from ..rates import FORMAT_VERSION
from ..storage import DataError, load_client, write_tsv

from .core import HEADERS, mutate_folder, save_rows, transaction
from .numbering import slugify
from .parse import _toml_str

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


