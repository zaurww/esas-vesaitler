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

# Written into each update's own backup_dir, so rollback_update can find it
# again later without re-deriving what changed from a "before" state that,
# by the time a rollback is requested, no longer exists on disk.
_MANIFEST = "_manifest.json"

# One marker per installation, not per update: only the most recent update
# can still be pending verification -- an update overwrites its predecessor's
# files, so an older marker would point at a backup_dir that is no longer
# "one step back" from what is on disk.
_PENDING_VERIFY = "pending_verify.json"


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
        # Which top-level entries existed before (backed up, and restorable
        # by rollback_update) versus were newly added by this update (nothing
        # to restore them FROM -- rollback_update deletes them instead,
        # because the old version never had them). Recorded rather than
        # re-derived at rollback time: by then the "before" state is gone,
        # overwritten by exactly the write this manifest is describing.
        replaced: list[str] = []
        added: list[str] = []
        for p in entries:
            dest = root / p.name
            if dest.exists():
                if dest.is_dir():
                    shutil.copytree(dest, backup_dir / p.name)
                    shutil.rmtree(dest)
                else:
                    shutil.copy2(dest, backup_dir / p.name)
                    dest.unlink()
                replaced.append(p.name)
            else:
                added.append(p.name)
            if p.is_dir():
                shutil.copytree(p, dest)
            else:
                shutil.copy2(p, dest)

        (backup_dir / _MANIFEST).write_text(json.dumps({
            "from_version": from_version, "to_version": to_version,
            "replaced": replaced, "added": added,
        }, ensure_ascii=False), encoding="utf-8")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    _write_pending_verify(root, backup_dir.name, from_version, to_version)

    return (f"Yeniləmə tətbiq olundu ({from_version} → {to_version or '?'}). "
            f"Brauzer sekmesini bağlamaq kifayət etmir — proqramın işlədiyi "
            f"QARA pəncərəni (konsol) bağlayın və «Başlat.bat»-ı yenidən açın.")


def _pending_verify_path(root: Path) -> Path:
    return root / "backups" / "_app" / _PENDING_VERIFY


def _write_pending_verify(root: Path, backup_dir_name: str,
                           from_version: str, to_version: str) -> None:
    """Leave a note for the NEXT process start: "check the closed years".

    Why a file and not just doing the check right here, inside apply_update:
    this process still has the OLD engine's modules already imported.
    Overwriting the .py files on disk does not change what is running in
    memory (the same reason self-restart is not attempted, CLAUDE.md §9) --
    a check run right now would verify the old engine against itself and
    always pass. The check that means something runs when the app is next
    started and actually imports the new code, which is web/app.py's job.
    """
    path = _pending_verify_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "backup_dir": backup_dir_name,
        "from_version": from_version,
        "to_version": to_version,
    }, ensure_ascii=False), encoding="utf-8")


def read_pending_verify(root: Path) -> dict | None:
    """Is there an update since the last successful post-update check?

    None both when there is nothing pending and when the marker is unreadable
    (deleted by hand, truncated by a crash mid-write) -- either way there is
    nothing this process can act on, and a startup check must not itself
    raise over a courtesy file (the same broad-except reasoning as
    check_latest's).
    """
    path = _pending_verify_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_pending_verify(root: Path) -> None:
    _pending_verify_path(root).unlink(missing_ok=True)


def rollback_update(root: Path, backup_dir: Path) -> str:
    """Undo one apply_update() by restoring what it replaced.

    Held to the same discipline apply_update itself follows -- and that
    engine.mutate.core.transaction follows for every client write (§8.1):
    back up what is about to be discarded before touching it, so a rollback
    is itself reversible rather than a second irreversible leap.

    Raises ValueError if backup_dir does not look like one of our own
    update backups -- refusing is the right failure here (§2.1); silently
    doing nothing while claiming success would leave the broken update in
    place with no way back.
    """
    manifest_path = backup_dir / _MANIFEST
    if not backup_dir.is_dir() or not manifest_path.is_file():
        raise ValueError(f"Bərpa nöqtəsi tapılmadı: {backup_dir.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    undo_dir = root / "backups" / "_app" / f"{stamp}-rollback-of-{backup_dir.name}"
    undo_dir.mkdir(parents=True)

    # Clear out the current (post-update) state first -- both what will be
    # restored from backup_dir and what this update added and has no
    # "before" version of at all.
    for name in [*manifest["replaced"], *manifest["added"]]:
        dest = root / name
        if not dest.exists():
            continue
        if dest.is_dir():
            shutil.copytree(dest, undo_dir / name)
            shutil.rmtree(dest)
        else:
            shutil.copy2(dest, undo_dir / name)
            dest.unlink()

    # Only "replaced" entries come back -- "added" ones simply stay removed,
    # because the version being rolled back TO never had them either.
    for name in manifest["replaced"]:
        src, dest = backup_dir / name, root / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    clear_pending_verify(root)
    return (f"Geri qaytarıldı ({manifest['to_version'] or '?'} → "
            f"{manifest['from_version']}). Brauzer sekmesini bağlamaq "
            f"kifayət etmir — proqramın işlədiyi QARA pəncərəni (konsol) "
            f"bağlayın və «Başlat.bat»-ı yenidən açın.")
