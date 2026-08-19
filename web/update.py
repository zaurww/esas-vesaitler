"""Check GitHub for a newer release and, on request, replace the app's own
source files with it (CLAUDE.md §9).

Distribution stays plain Python source (Başlat.bat + `python ev.py`), not a
compiled .exe: overwriting a .py file on disk is safe once Python has
already read it -- no lock survives import, unlike a running .exe -- so no
helper process or self-restart is needed. The trade-off this accepts: the
worker still needs Python installed once; a compiled, single-file
distribution is a separate task that has not been started (CLAUDE.md §9).

Two halves, deliberately unequal in how failure is treated:

* check_latest() is a courtesy, run once on every page load (§9). A worker
  offline, or GitHub unreachable, must not interrupt opening the program or
  announce an error -- it just means no banner. Every failure path returns
  {"available": False} rather than raising, which is why it swallows
  Exception broadly: unlike the rest of this codebase (§2.1 -- a failed
  calculation must be loud), a failed network courtesy must be silent.
* apply_update() is a real write to the installation and is held to a
  discipline like engine.mutate.core.transaction's: back up what is about
  to be overwritten before touching it. It is NOT that transaction, though
  -- no client, no changelog line, no per-year recompute to verify against;
  it operates on the installation root itself, not on clients/<slug>/.
"""

from __future__ import annotations

import io
import json
import shutil
import urllib.error
import urllib.request
import zipfile

from datetime import datetime
from pathlib import Path
from typing import Callable

from engine.rates import ENGINE_VERSION, version_tuple

GITHUB_REPO = "zaurww/esas-vesaitler"
# Hardcoded rather than read from `git remote`: a worker's copy is an
# extracted zip, not a clone -- there is no .git to read at runtime.
_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# What an update must NEVER touch. A denylist, not an allowlist: the same
# reasoning as rates.NORM_FILES and import.js's GRID_COLS being named once
# -- an allowlist of "what to replace" would need a new entry every time the
# app grows a file and would eventually be forgotten (as NORM_FILES itself
# once was, CLAUDE.md §5.1). A short "what to keep" list is stable instead.
PRESERVE = {"clients", "backups", "rates.tsv", "coefficients.tsv",
            "parameters.tsv", "categories.tsv"}


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "EsasVesaitler-update-check",
    })
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "EsasVesaitler-update-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def check_latest(fetch: Callable[[str], dict] = _http_get_json) -> dict:
    """Is there a release on GitHub newer than ENGINE_VERSION?

    `fetch` is injectable so tests can hand it a canned response or one that
    raises (offline) without a real network call (§11.4 -- the suite stays
    network-free).
    """
    try:
        rel = fetch(_API_URL)
        tag = str(rel["tag_name"])
        zip_url = str(rel["zipball_url"])
    except Exception:
        # Anything at all -- DNS failure, timeout, malformed JSON, a rate
        # limit, a repo with no releases yet -- means "no banner", never an
        # error dialog over a tax calculation screen.
        return {"current": ENGINE_VERSION, "latest": None,
                "available": False, "url": _RELEASES_URL}
    return {
        "current": ENGINE_VERSION,
        "latest": tag.lstrip("vV"),
        "available": version_tuple(tag) > version_tuple(ENGINE_VERSION),
        "url": rel.get("html_url", _RELEASES_URL),
        "zip_url": zip_url,
    }


def download(zip_url: str, fetch: Callable[[str], bytes] = _http_get_bytes) -> bytes:
    return fetch(zip_url)


def apply_update(root: Path, zip_bytes: bytes, *,
                  from_version: str = ENGINE_VERSION,
                  to_version: str = "") -> str:
    """Replace the app's own files with what is in zip_bytes.

    zip_bytes is a GitHub-generated source zip (the "zipball" every Release
    carries automatically) -- one top-level folder GitHub names
    "<owner>-<repo>-<short-sha>/", containing the tracked files at that tag.
    The same set `git archive` produces, already used once in this project
    to hand a client a folder by hand (CLAUDE.md §9).

    Raises ValueError on a zip that plainly is not this kind of archive,
    rather than silently doing nothing -- an update that reports success
    without changing anything is worse than one that refuses (§2.1).
    """
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = [n for n in z.namelist() if n.strip()]
    if not names:
        raise ValueError("Arxiv boşdur")
    top = names[0].split("/", 1)[0]
    if not top or any(not n.startswith(top + "/") for n in names):
        raise ValueError("Arxivin gözlənilən quruluşu yoxdur (GitHub zipball deyil?)")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    app_backups = root / "backups" / "_app"
    backup_dir = app_backups / f"{stamp}-update-{from_version}-to-{to_version or 'naməlum'}"
    extract_dir = app_backups / f"{stamp}-incoming"
    extract_dir.mkdir(parents=True)
    try:
        z.extractall(extract_dir)
        src_root = extract_dir / top
        entries = [p for p in sorted(src_root.iterdir())
                   if p.name not in PRESERVE and p.name != ".git"]
        if not entries:
            raise ValueError("Yenilənəcək fayl tapılmadı")

        backup_dir.mkdir(parents=True)
        for p in entries:
            dest = root / p.name
            if dest.exists():
                if dest.is_dir():
                    shutil.copytree(dest, backup_dir / p.name)
                    shutil.rmtree(dest)
                else:
                    shutil.copy2(dest, backup_dir / p.name)
                    dest.unlink()
            if p.is_dir():
                shutil.copytree(p, dest)
            else:
                shutil.copy2(p, dest)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return (f"Yeniləmə tətbiq olundu ({from_version} → {to_version or '?'}). "
            f"Pəncərəni bağlayıb «Başlat.bat»-ı yenidən açın.")
