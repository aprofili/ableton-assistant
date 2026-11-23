"""Auto-update from GitHub releases (stdlib only).

check() -> latest release tag if newer than VERSION. install() downloads the release source zip, backs up
replaced files to .update_backup/, copies the new files over this folder (never touching .venv, config.json,
.env, logs, data/learned_shortcuts.json, data/feedback), re-runs pip if requirements.txt changed, then restarts.
If the new version crashes on start, start_tray.pyw calls rollback_on_crash() to restore the backup.
Private repo: put GITHUB_TOKEN=<fine-grained read-only token, Contents: read> in .env.
"""
import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

from . import __version__
from . import config as cfgmod

log = logging.getLogger("assistant")
ROOT = cfgmod.ROOT
REPO = "aprofili/ableton-assistant"
BACKUP = os.path.join(ROOT, ".update_backup")
PENDING = os.path.join(ROOT, ".update_pending")
PROTECT = (".venv", "config.json", ".env", "logs", ".update_backup", ".update_pending",
           os.path.join("data", "learned_shortcuts.json"), os.path.join("data", "feedback"), os.path.join("data", "ui_state.json"), os.path.join("data", "learned_macros.json"), "__pycache__", ".git")


def _vt(v):
    out = []
    for p in v.strip().lstrip("v").split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def _token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def _get(url, accept="application/vnd.github+json"):
    h = {"Accept": accept, "User-Agent": "ableton-assistant-updater"}
    t = _token()
    if t:
        h["Authorization"] = f"Bearer {t}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return r.read()


def check():
    """Returns (tag, zip_url) when a newer release exists, else None. Raises on network/auth problems."""
    rel = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/latest"))
    tag = rel["tag_name"]
    if _vt(tag) > _vt(__version__):
        return tag, rel["zipball_url"]
    return None


def _protected(rel):
    rel = rel.replace("/", os.sep)
    return any(rel == p or rel.startswith(p + os.sep) for p in PROTECT)


def apply_zip(data, root=ROOT, backup=BACKUP):
    """Extract release zip bytes over root. Returns True if requirements.txt changed."""
    def req_hash():
        try:
            with open(os.path.join(root, "requirements.txt"), "rb") as f:
                return hashlib.sha1(f.read()).hexdigest()
        except OSError:
            return None
    before = req_hash()
    if os.path.isdir(backup):
        shutil.rmtree(backup)
    os.makedirs(backup)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            rel = parts[1].replace("/", os.sep)
            if _protected(rel):
                continue
            dest = os.path.join(root, rel)
            if os.path.exists(dest):
                bk = os.path.join(backup, rel)
                os.makedirs(os.path.dirname(bk), exist_ok=True)
                shutil.copy2(dest, bk)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    return req_hash() != before


def _pip(root=ROOT):
    py = os.path.join(root, ".venv", "Scripts", "python.exe")
    if os.path.exists(py):
        subprocess.run([py, "-m", "pip", "install", "-r", os.path.join(root, "requirements.txt")],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=900)


def restart():
    """Relaunch hidden after this process exits (so the single-instance mutex is free)."""
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe") if py.lower().endswith("python.exe") else py
    code = ("import time,subprocess;time.sleep(3);"
            f"subprocess.Popen([{pyw!r},{os.path.join(ROOT, 'start_tray.pyw')!r}],cwd={ROOT!r},"
            "creationflags=0x08000000|0x00000008)")
    subprocess.Popen([pyw, "-c", code], creationflags=0x08000000 | 0x00000008, close_fds=True)
    os._exit(0)


def install(tag, url):
    log.info("Updating to %s...", tag)
    data = _get(url, accept="application/vnd.github+json")
    with open(PENDING, "w", encoding="utf-8") as f:
        f.write(json.dumps({"from": __version__, "to": tag, "time": time.time()}))
    if apply_zip(data):
        log.info("requirements.txt changed; installing packages")
        _pip()
    log.info("Update %s installed; restarting", tag)


def confirm():
    """Called once the new version reached 'Ready': drop the rollback marker."""
    try:
        os.remove(PENDING)
    except OSError:
        pass


def rollback_on_crash():
    """Called from start_tray.pyw when startup raised. Restores the backup if an update was pending."""
    if not (os.path.exists(PENDING) and os.path.isdir(BACKUP)):
        return False
    for dp, _, fs in os.walk(BACKUP):
        for fn in fs:
            src = os.path.join(dp, fn)
            dest = os.path.join(ROOT, os.path.relpath(src, BACKUP))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
    os.remove(PENDING)
    return True
