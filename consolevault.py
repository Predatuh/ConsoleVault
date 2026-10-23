#!/usr/bin/env python3
"""
ConsoleVault - all-in-one emulator hub for Windows.

Folder layout (created automatically next to ConsoleVault.exe):
    emulators/<emulator>/   <- unzip each emulator here
    roms/<console>/         <- your games go here (or use "Add Games")
    consolevault_config.json      <- your settings (exe overrides, args, custom ROM folders)
"""
import os
import sys
import json
import re
import zipfile
import urllib.parse
import shlex
import shutil
import subprocess
import tempfile
import webbrowser
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QObject, QEvent, QThread, Signal, QProcess
from PySide6.QtGui import QFont, QKeyEvent, QWindow, QShortcut, QKeySequence, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QStackedWidget, QLineEdit,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QProgressDialog, QAbstractItemView, QTreeWidget, QTreeWidgetItem, QProgressBar, QPlainTextEdit,
)

IS_WIN = sys.platform.startswith("win")
APP_NAME = "ConsoleVault"
VERSION = "__VERSION__"          # stamped by the GitHub build
UPDATE_REPO = "__REPO__"         # e.g. tanner/ConsoleVault, stamped by the GitHub build
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
SETTINGS_FILE = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME / "location.json"

# Library = where emulators/, roms/ and the config live. Set by set_library().
BASE = EMU_DIR = ROM_DIR = CFG_PATH = None


def set_library(path):
    global BASE, EMU_DIR, ROM_DIR, CFG_PATH
    BASE = Path(path)
    EMU_DIR = BASE / "emulators"
    ROM_DIR = BASE / "roms"
    CFG_PATH = BASE / "consolevault_config.json"
    BASE.mkdir(parents=True, exist_ok=True)


def saved_library():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("library")
    except Exception:
        return None


def save_library(path):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({"library": str(path)}), encoding="utf-8")


def choose_library(parent=None, first_run=False):
    default = Path.home() / APP_NAME
    msg = ("Where should ConsoleVault keep your emulators and games?\n\n"
           f"Default: {default}\n\n"
           "If you already have an emulators/roms folder from before, choose “Pick folder…” and select it.")
    box = QMessageBox(parent)
    box.setWindowTitle(APP_NAME)
    box.setText(msg)
    use_default = box.addButton("Use default", QMessageBox.AcceptRole)
    pick = box.addButton("Pick folder…", QMessageBox.ActionRole)
    if not first_run:
        box.addButton(QMessageBox.Cancel)
    box.exec()
    if box.clickedButton() is use_default:
        return default
    if box.clickedButton() is pick:
        d = QFileDialog.getExistingDirectory(parent, "Pick your ConsoleVault library folder", str(Path.home()))
        if d:
            return Path(d)
        return default if first_run else None
    return None


def version_tuple(v):
    out = []
    for part in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def updates_enabled():
    return FROZEN and IS_WIN and "__" not in VERSION and "__" not in UPDATE_REPO

# ---------------------------------------------------------------------------
# Console / emulator catalogue.  "{rom}" in args is replaced by the game path.
# exes: file names ConsoleVault looks for inside emulators/<folder>/ (first match wins)
# ---------------------------------------------------------------------------
SYSTEMS = [
    dict(id="nes", short="NES", name="Nintendo Entertainment System", emu="Mesen", folder="mesen",
         exes=["Mesen.exe"], args=["{rom}"], ext=[".nes", ".fds", ".unf", ".zip"],
         url="https://www.mesen.ca/", color="#e53935"),
    dict(id="snes", short="SNES", name="Super Nintendo", emu="Mesen", folder="mesen",
         exes=["Mesen.exe"], args=["{rom}"], ext=[".sfc", ".smc", ".zip"],
         url="https://www.mesen.ca/", color="#8e24aa"),
    dict(id="gb", short="Game Boy / Color", name="Game Boy & Game Boy Color", emu="mGBA", folder="mgba",
         exes=["mGBA.exe"], args=["-f", "{rom}"], ext=[".gb", ".gbc", ".zip"],
         url="https://mgba.io/downloads.html", color="#7cb342"),
    dict(id="gba", short="GBA", name="Game Boy Advance", emu="mGBA", folder="mgba",
         exes=["mGBA.exe"], args=["-f", "{rom}"], ext=[".gba", ".zip"],
         url="https://mgba.io/downloads.html", color="#5e35b1"),
    dict(id="n64", short="N64", name="Nintendo 64", emu="Rosalie's Mupen GUI (RMG)", folder="rmg",
         exes=["RMG.exe"], args=["--fullscreen", "{rom}"], ext=[".z64", ".n64", ".v64", ".zip"],
         url="https://github.com/Rosalie241/RMG/releases", color="#43a047"),
    dict(id="nds", short="DS", name="Nintendo DS", emu="melonDS", folder="melonds",
         exes=["melonDS.exe"], args=["{rom}"], ext=[".nds", ".zip"],
         url="https://melonds.kuribo64.net/downloads.php", color="#90a4ae"),
    dict(id="3ds", short="3DS", name="Nintendo 3DS", emu="Azahar", folder="azahar",
         exes=["azahar.exe", "azahar-qt.exe", "lime3ds.exe", "citra-qt.exe"], args=["{rom}"],
         ext=[".3ds", ".cci", ".cxi", ".3dsx", ".app", ".zcci", ".zcxi"],
         url="https://azahar-emu.org/", color="#d81b60"),
    dict(id="gc", short="GameCube", name="Nintendo GameCube", emu="Dolphin", folder="dolphin",
         exes=["Dolphin.exe"], args=["-b", "-e", "{rom}"], ext=[".iso", ".gcm", ".rvz", ".ciso", ".gcz", ".dol"],
         url="https://dolphin-emu.org/download/", color="#6a1b9a"),
    dict(id="wii", short="Wii", name="Nintendo Wii", emu="Dolphin", folder="dolphin",
         exes=["Dolphin.exe"], args=["-b", "-e", "{rom}"], ext=[".iso", ".wbfs", ".rvz", ".wad", ".ciso", ".gcz"],
         url="https://dolphin-emu.org/download/", color="#29b6f6"),
    dict(id="wiiu", short="Wii U", name="Nintendo Wii U", emu="Cemu", folder="cemu",
         exes=["Cemu.exe"], args=["-f", "-g", "{rom}"], ext=[".wua", ".wud", ".wux", ".rpx"],
         url="https://cemu.info/", color="#039be5"),
    dict(id="switch", short="Switch", name="Nintendo Switch", emu="Ryujinx (Ryubing)", folder="ryujinx",
         exes=["Ryujinx.exe"], args=["{rom}", "--fullscreen"], ext=[".nsp", ".xci", ".nca", ".nro"],
         url="https://ryujinx.app/", color="#e60012"),
    dict(id="ps1", short="PS1", name="PlayStation", emu="DuckStation", folder="duckstation",
         exes=["duckstation-qt-x64-ReleaseLTCG.exe", "duckstation-qt.exe"], args=["-fullscreen", "--", "{rom}"],
         ext=[".cue", ".chd", ".m3u", ".pbp", ".iso", ".bin", ".ecm"],
         url="https://www.duckstation.org/", color="#9e9e9e"),
    dict(id="ps2", short="PS2", name="PlayStation 2", emu="PCSX2", folder="pcsx2",
         exes=["pcsx2-qt.exe", "pcsx2-qtx64-avx2.exe", "pcsx2-qtx64.exe"], args=["-fullscreen", "--", "{rom}"],
         ext=[".iso", ".chd", ".cso", ".zso", ".bin", ".gz", ".elf"],
         url="https://pcsx2.net/downloads", color="#1e88e5"),
    dict(id="ps3", short="PS3", name="PlayStation 3", emu="RPCS3", folder="rpcs3",
         exes=["rpcs3.exe"], args=["--no-gui", "{rom}"], ext=[".iso", ".pkg"], folder_games="ps3",
         url="https://rpcs3.net/download", color="#3949ab",
         note="Disc games can be ISO or extracted folders (with PS3_GAME/USRDIR/EBOOT.BIN). "
              "Install the PS3 firmware once from inside RPCS3."),
    dict(id="psp", short="PSP", name="PlayStation Portable", emu="PPSSPP", folder="ppsspp",
         exes=["PPSSPPWindows64.exe", "PPSSPPWindows.exe"], args=["{rom}", "--fullscreen"],
         ext=[".iso", ".cso", ".chd", ".pbp", ".elf"],
         url="https://www.ppsspp.org/download/", color="#fb8c00"),
    dict(id="vita", short="PS Vita", name="PlayStation Vita", emu="Vita3K", folder="vita3k",
         exes=["Vita3K.exe"], args=[], ext=[".vpk", ".zip"],
         url="https://vita3k.org/", color="#00897b",
         note="Vita games are installed inside Vita3K (File > Install). Play opens Vita3K."),
    dict(id="xbox", short="Xbox", name="Original Xbox", emu="xemu", folder="xemu",
         exes=["xemu.exe"], args=["-dvd_path", "{rom}"], ext=[".iso", ".xiso"],
         url="https://xemu.app/", color="#2e7d32"),
    dict(id="x360", short="Xbox 360", name="Xbox 360", emu="Xenia Canary", folder="xenia",
         exes=["xenia_canary.exe", "xenia.exe"], args=["{rom}"], ext=[".iso", ".xex", ".zar"],
         url="https://xenia.jp/download/", color="#76b900"),
    dict(id="dc", short="Dreamcast", name="Sega Dreamcast", emu="Flycast", folder="flycast",
         exes=["flycast.exe"], args=["{rom}"], ext=[".chd", ".gdi", ".cdi", ".cue"],
         url="https://github.com/flyinghead/flycast/releases", color="#f4511e"),
]

DISC_SHEETS = {".cue", ".m3u", ".gdi"}
SHEET_TRACKS = {".bin", ".img", ".raw", ".iso"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def open_path(p: Path):
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True) if not p.suffix else None
    try:
        if IS_WIN:
            os.startfile(str(p))  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:  # pragma: no cover
        QMessageBox.warning(None, APP_NAME, f"Couldn't open {p}\n{e}")


def clean_child_env() -> dict:
    """Environment for launched emulators, minus everything the packaged exe injected.
    Without this, Qt-based emulators (RPCS3, PCSX2, DuckStation, Dolphin...) pick up
    ConsoleVault's temp-folder DLLs and Qt plugins and crash."""
    env = dict(os.environ)
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        mei_n = os.path.normcase(os.path.abspath(mei))
        for key in ("PATH",):
            parts = env.get(key, "").split(os.pathsep)
            env[key] = os.pathsep.join(p for p in parts
                                       if p and not os.path.normcase(os.path.abspath(p)).startswith(mei_n))
        for k in list(env):
            if mei_n in os.path.normcase(env[k]):
                env.pop(k, None)
    for k in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH",
              "QT_QPA_PLATFORM", "PYTHONHOME", "PYTHONPATH", "_PYI_APPLICATION_HOME_DIR",
              "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL", "_MEIPASS2"):
        env.pop(k, None)
    return env


class UpdateChecker(QThread):
    found = Signal(str, str)  # new version, installer url

    def run(self):
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json", "User-Agent": APP_NAME})
            data = json.load(urllib.request.urlopen(req, timeout=15))
            tag = data.get("tag_name", "")
            if version_tuple(tag) > version_tuple(VERSION):
                for a in data.get("assets", []):
                    if a["name"].lower().endswith("setup.exe"):
                        self.found.emit(tag.lstrip("vV"), a["browser_download_url"])
                        return
        except Exception:
            pass  # offline / rate-limited: try again later


class Downloader(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url, dest):
        super().__init__()
        self.url, self.dest = url, dest

    def run(self):
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": APP_NAME})
            with urllib.request.urlopen(req, timeout=30) as r, open(self.dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while chunk := r.read(256 * 1024):
                    f.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
            self.done.emit(self.dest)
        except Exception as e:
            self.failed.emit(str(e))


def detect_exe(s) -> Path | None:
    folder = EMU_DIR / s["folder"]
    if not folder.exists():
        return None
    wanted = [n.lower() for n in s["exes"]]
    best, best_rank = None, 999
    for root, dirs, files in os.walk(folder):
        if len(Path(root).relative_to(folder).parts) >= 3:
            dirs[:] = []
        for f in files:
            fl = f.lower()
            if fl in wanted and wanted.index(fl) < best_rank:
                best, best_rank = Path(root) / f, wanted.index(fl)
    return best


def find_folder_game(kind: str, d: Path) -> Path | None:
    if kind == "ps3":
        for cand in (d / "PS3_GAME" / "USRDIR" / "EBOOT.BIN", d / "USRDIR" / "EBOOT.BIN"):
            if cand.exists():
                return cand
    return None


def scan_games(s, rom_dir: Path):
    """Returns list of (display_name, launch_path)."""
    games = []
    if not rom_dir.exists():
        return games
    exts = {e.lower() for e in s["ext"]}

    def scan_dir(d: Path, depth: int):
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        files = [p for p in entries if p.is_file() and p.suffix.lower() in exts]
        sufs = {p.suffix.lower() for p in files}
        if sufs & DISC_SHEETS:  # hide raw track files when a cue/m3u/gdi describes them
            hide = SHEET_TRACKS | ({".cue", ".chd"} if ".m3u" in sufs else set())
            files = [p for p in files if p.suffix.lower() not in hide]
        for p in files:  # a lone game inside its own folder is named after the folder
            games.append((d.name if depth > 0 and len(files) == 1 else p.stem, p))
        if depth >= 2:
            return
        for sub in (p for p in entries if p.is_dir()):
            if s.get("folder_games"):
                g = find_folder_game(s["folder_games"], sub)
                if g:
                    games.append((sub.name, g))
                    continue
            scan_dir(sub, depth + 1)

    scan_dir(rom_dir, 0)
    return games


# ---------------------------------------------------------------------------
# Windows window-embedding helpers (used by "Open Inside")
# ---------------------------------------------------------------------------
try:  # ctypes powers window embedding + controller; app still works without it
    import ctypes
    import ctypes.wintypes as wt
    HAS_CT = IS_WIN
except ImportError:
    HAS_CT = False

if HAS_CT:
    user32 = ctypes.windll.user32
    user32.GetWindow.restype = wt.HWND
    _EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def find_window_for_pid(pid: int):
        found = []

        def cb(hwnd, _lp):
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if (p.value == pid and user32.IsWindowVisible(hwnd)
                    and not user32.GetWindow(hwnd, 4)  # GW_OWNER
                    and user32.GetWindowTextLengthW(hwnd) > 0):
                found.append(hwnd)
                return False
            return True

        proc = _EnumProc(cb)
        user32.EnumWindows(proc, 0)
        return found[0] if found else None

    def restore_toplevel(hwnd):
        GWL_STYLE, WS_CHILD, WS_OVERLAPPEDWINDOW, WS_VISIBLE = -16, 0x40000000, 0x00CF0000, 0x10000000
        user32.SetParent(hwnd, None)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~WS_CHILD) | WS_OVERLAPPEDWINDOW | WS_VISIBLE)
        user32.SetWindowPos(hwnd, None, 100, 100, 1280, 760, 0x0020 | 0x0040)  # FRAMECHANGED|SHOWWINDOW
        user32.SetForegroundWindow(hwnd)
else:
    def find_window_for_pid(pid):
        return None

    def restore_toplevel(hwnd):
        pass


# ---------------------------------------------------------------------------
# Xbox-style controller support via XInput (Windows only)
# ---------------------------------------------------------------------------
class Gamepad(QObject):
    BTN = {0x0001: "up", 0x0002: "down", 0x0004: "left", 0x0008: "right", 0x0010: "start",
           0x0020: "back", 0x0100: "lb", 0x0200: "rb", 0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y"}
    REPEATABLE = {"up", "down", "left", "right"}

    def __init__(self, handler):
        super().__init__()
        self.handler = handler
        self.xinput = None
        if HAS_CT:
            for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
                try:
                    self.xinput = getattr(ctypes.windll, dll)
                    break
                except OSError:
                    continue
        if not self.xinput:
            return

        class GP(ctypes.Structure):
            _fields_ = [("wButtons", wt.WORD), ("bLT", ctypes.c_ubyte), ("bRT", ctypes.c_ubyte),
                        ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]

        class ST(ctypes.Structure):
            _fields_ = [("packet", wt.DWORD), ("gp", GP)]

        self.state = ST()
        self.held = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(40)

    def poll(self):
        pressed = set()
        for i in range(4):
            if self.xinput.XInputGetState(i, ctypes.byref(self.state)) == 0:
                b, gp = self.state.gp.wButtons, self.state.gp
                pressed |= {n for m, n in self.BTN.items() if b & m}
                if gp.ly > 16000: pressed.add("up")
                if gp.ly < -16000: pressed.add("down")
                if gp.lx < -16000: pressed.add("left")
                if gp.lx > 16000: pressed.add("right")
        now = QTimerClock.now()
        for name in pressed:
            if name not in self.held:
                self.held[name] = now + 400
                self.handler(name)
            elif name in self.REPEATABLE and now >= self.held[name]:
                self.held[name] = now + 110
                self.handler(name)
        for name in list(self.held):
            if name not in pressed:
                del self.held[name]


class QTimerClock:
    from time import monotonic as _m

    @staticmethod
    def now():
        return int(QTimerClock._m() * 1000)


# ---------------------------------------------------------------------------
# Emulator auto-install / auto-detect / BIOS import
# ---------------------------------------------------------------------------
GH, SCRAPE, GL, FJ = "github", "scrape", "gitlab", "forgejo"

# key = folder name under emulators/.  src: (GH, owner/repo[, fixed_tag]) or (SCRAPE, page, regex(url, version))
EMULATORS = {
    "mesen": dict(name="Mesen", src=(GH, "SourMesen/Mesen2"), match=["win"]),
    "mgba": dict(name="mGBA", src=(GH, "mgba-emu/mgba"), match=["win64"], avoid=["installer", "setup"]),
    "rmg": dict(name="RMG", src=(GH, "Rosalie241/RMG"), match=["windows"], prefer=["portable"],
                avoid=["setup", "installer"]),
    "melonds": dict(name="melonDS", src=(GH, "melonDS-emu/melonDS"), match=["win"]),
    "azahar": dict(name="Azahar", src=(GH, "azahar-emu/azahar"), match=["windows"], prefer=["msvc"],
                   avoid=["installer", "setup"], portable_dirs=["user"]),
    "dolphin": dict(name="Dolphin", src=[
        (SCRAPE, "https://dolphin-emu.org/download/",
         r'((?:https:)?//dl\.dolphin-emu\.org/releases/(\d+)/dolphin-\d+-x64\.7z)'),
        (SCRAPE, "https://dolphin-emu.org/download/list/releases/1/",
         r'((?:https:)?//dl\.dolphin-emu\.org/releases/(\d+)/dolphin-\d+-x64\.7z)')],
                    portable_files=["portable.txt"]),
    "cemu": dict(name="Cemu", src=(GH, "cemu-project/Cemu"), match=["windows"], portable_dirs=["portable"]),
    "ryujinx": dict(name="Ryujinx", src=[(FJ, "https://git.ryujinx.app", "Ryubing/Stable-Releases"),
                                         (FJ, "https://git.ryujinx.app", "Ryubing/Stable"),
                                         (FJ, "https://git.ryujinx.app", "Ryubing/Ryujinx"),
                                         (GL, "https://git.ryujinx.app", "ryubing/ryujinx")],
                    match=["win"], avoid=["canary"],
                    portable_dirs=["portable"]),
    "duckstation": dict(name="DuckStation", src=(GH, "stenzek/duckstation"), match=["windows", "x64"],
                        prefer=["release"], avoid=["sse2"], prerelease=True, portable_files=["portable.txt"]),
    "pcsx2": dict(name="PCSX2", src=(GH, "PCSX2/pcsx2"), match=["windows"], prefer=["qt"],
                  portable_files=["portable.ini"]),
    "rpcs3": dict(name="RPCS3", src=(GH, "RPCS3/rpcs3-binaries-win"), match=["win64"], needs=["vcredist", "ps3fw"]),
    "ppsspp": dict(name="PPSSPP", src=(SCRAPE, "https://www.ppsspp.org/download/",
                                       r'((?:https://www\.ppsspp\.org)?/files/(\d+_\d+(?:_\d+)?)/ppsspp_win\.zip)')),
    "vita3k": dict(name="Vita3K", src=(GH, "Vita3K/Vita3K", "continuous"), match=["windows"]),
    "xemu": dict(name="xemu", src=(GH, "xemu-project/xemu"), match=["win"], prefer=["release", "x86_64"],
                 avoid=["dbg"], needs=["xemuhdd"]),
    "xenia": dict(name="Xenia Canary", src=(GH, "xenia-canary/xenia-canary-releases"), match=["windows"],
                  needs=["vcredist"], portable_files=["portable.txt"]),
    "flycast": dict(name="Flycast", src=(GH, "flyinghead/flycast"), match=["win64"]),
}
DEFAULT_AVOID = ["arm64", "aarch64", "arm32", "armv7", "linux", "darwin", "macos", "-mac", "_mac", "osx", "android",
                 "apple", "debug", "pdb", "symbols", "dbgsym", "source", "appimage", "flatpak", "headless"]
ROLLING_TAGS = {"latest", "continuous", "nightly", "preview"}

PS3_UPDATE_LIST = "http://fus01.ps3.update.playstation.net/update/ps3/list/us/ps3-updatelist.txt"
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
XEMU_HDD_URL = "https://github.com/xemu-project/xemu-hdd-image/releases/latest/download/xbox_hdd.qcow2.zip"

# What each console still needs that can't be downloaded (shown in the setup window)
BIOS_NOTES = {
    "duckstation": "PS1 BIOS from your console (import it below)",
    "pcsx2": "PS2 BIOS from your console (import it below)",
    "rpcs3": "PS3 firmware — downloaded from Sony automatically",
    "ryujinx": "prod.keys + firmware from your Switch (import keys below)",
    "xemu": "MCPX boot ROM + BIOS from your Xbox (import below)",
    "cemu": "keys.txt only for encrypted dumps (optional)",
    "vita3k": "Vita3K offers Sony's firmware download on first launch",
}

# (filename regex, exact size or None, emulator folder, sub-folder)
BIOS_RULES = [
    (r"^(prod|title)\.keys$", None, "ryujinx", "portable/system"),
    (r"^keys\.txt$", None, "cemu", ""),
    (r"^(bios7|bios9|firmware|dsi_bios7|dsi_bios9|dsi_firmware|dsi_nand)\.bin$", None, "melonds", ""),
    (r"^gba_bios\.bin$", None, "mgba", ""),
    (r"^dc_(boot|flash|nvmem)\.bin$", None, "flycast", "data"),
    (r"^(mcpx.*|complex.*|.*xbox.*bios.*|.*cromwell.*)\.bin$", None, "xemu", "bios"),
    (r"\.bin$", 512 * 1024, "duckstation", "bios"),       # PS1 BIOS = 512 KB
    (r"\.(bin|rom0)$", 4 * 1024 * 1024, "pcsx2", "bios"),  # PS2 BIOS = 4 MB
]


def http_get(url, timeout=30):
    headers = {"User-Agent": f"{APP_NAME}/{VERSION}"}
    if "github" not in url and "gitlab" not in url and "/api/" not in url:
        headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        headers["Accept"] = "text/html,application/xhtml+xml,*/*"
    if "api.github.com" in url:
        headers["Accept"] = "application/vnd.github+json"
        tok = os.environ.get("CV_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def folder_exes(key):
    names = []
    for s in SYSTEMS:
        if s["folder"] == key:
            names += [n for n in s["exes"] if n not in names]
    return names


def find_exe_in(folder: Path, names):
    if not folder.exists():
        return None
    wanted = [n.lower() for n in names]
    best, rank = None, 999
    for root, dirs, files in os.walk(folder):
        if len(Path(root).relative_to(folder).parts) >= 3:
            dirs[:] = []
        for f in files:
            fl = f.lower()
            if fl in wanted and wanted.index(fl) < rank:
                best, rank = Path(root) / f, wanted.index(fl)
    return best


def pick_asset(assets, e):
    best = None
    for a in assets:
        n = a["name"].lower()
        if not (n.endswith(".zip") or n.endswith(".7z")):
            continue
        if any(t not in n for t in e.get("match", [])):
            continue
        if any(t in n for t in DEFAULT_AVOID + e.get("avoid", [])):
            continue
        score = sum(2 for t in e.get("prefer", []) if t in n) + (1 if n.endswith(".zip") else 0) - len(n) / 1000
        if best is None or score > best[0]:
            best = (score, a)
    return best[1] if best else None


def resolve_latest(key):
    """-> dict(version, url, name) for the newest stable Windows build. Tries each source in turn."""
    e = EMULATORS[key]
    sources = e["src"] if isinstance(e["src"], list) else [e["src"]]
    errors = []
    for src in sources:
        try:
            return resolve_from(e, src)
        except Exception as ex:
            errors.append(f"{src[1]}: {ex}")
    raise RuntimeError(" | ".join(errors))


def resolve_from(e, src):
    if src[0] == GL:
        proj = urllib.parse.quote(src[2], safe="")
        rels = json.load(http_get(f"{src[1]}/api/v4/projects/{proj}/releases?per_page=20"))
        for rel in rels:
            if rel.get("upcoming_release"):
                continue
            assets = [dict(name=l.get("name") or l["url"].rsplit("/", 1)[-1],
                           browser_download_url=l.get("direct_asset_url") or l["url"])
                      for l in rel.get("assets", {}).get("links", [])]
            a = pick_asset(assets, e)
            if a:
                return dict(version=rel.get("tag_name") or rel.get("name"), url=a["browser_download_url"],
                            name=a["name"])
        raise RuntimeError("no Windows download in its releases")
    if src[0] in (GH, FJ):
        if src[0] == FJ:  # Forgejo/Gitea speak the same release API as GitHub
            base, src = f"{src[1]}/api/v1/repos/{src[2]}/releases", (FJ, src[2])
        else:
            base = f"https://api.github.com/repos/{src[1]}/releases"
        if len(src) > 2:
            releases = [json.load(http_get(f"{base}/tags/{src[2]}"))]
        else:
            releases = []
            try:
                releases.append(json.load(http_get(base + "/latest")))
            except Exception:
                pass
            releases += json.load(http_get(base + "?per_page=20"))
        for rel in releases:
            if rel.get("draft"):
                continue
            tag = rel.get("tag_name") or ""
            if rel.get("prerelease") and not (e.get("prerelease") or len(src) > 2 or tag.lower() in ROLLING_TAGS):
                continue
            a = pick_asset(rel.get("assets", []), e)
            if a:
                ver = tag or rel.get("name") or "?"
                if tag.lower() in ROLLING_TAGS or len(src) > 2:
                    ver = "build " + (a.get("updated_at") or rel.get("published_at") or "")[:10]
                return dict(version=ver, url=a["browser_download_url"], name=a["name"])
        raise RuntimeError("no Windows download found on its releases page")
    page = http_get(src[1]).read().decode("utf-8", "replace")
    m = re.search(src[2], page)
    if not m:
        raise RuntimeError("couldn't find the Windows download on " + src[1])
    url = urllib.parse.urljoin(src[1], m.group(1))
    return dict(version=m.group(2).replace("_", "."), url=url, name=url.rsplit("/", 1)[-1])


def download_file(url, dest, progress=None, cancelled=lambda: False):
    with http_get(url, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while chunk := r.read(512 * 1024):
            if cancelled():
                raise RuntimeError("cancelled")
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    return dest


def seven_zip():
    for d in (Path(getattr(sys, "_MEIPASS", APP_DIR)), APP_DIR):
        if (d / "7zr.exe").exists():
            return d / "7zr.exe"
    return shutil.which("7z") or shutil.which("7zr")


def extract_archive(archive: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
        return
    sz = seven_zip()
    if not sz:
        raise RuntimeError("7-Zip helper missing - can't open .7z files")
    r = subprocess.run([str(sz), "x", "-y", f"-o{out}", str(archive)], capture_output=True, text=True,
                       creationflags=0x08000000 if IS_WIN else 0)
    if r.returncode != 0:
        raise RuntimeError("extract failed: " + (r.stderr or r.stdout)[-300:])


def merge_tree(src_dir: Path, dest: Path):
    items = list(src_dir.iterdir())
    while len(items) == 1 and items[0].is_dir():  # strip a single wrapper folder
        src_dir = items[0]
        items = list(src_dir.iterdir())
    dest.mkdir(parents=True, exist_ok=True)
    for p in items:
        t = dest / p.name
        if p.is_dir():
            shutil.copytree(p, t, dirs_exist_ok=True)
        else:
            shutil.copy2(p, t)


def vcredist_installed():
    if not IS_WIN:
        return True
    try:
        import winreg
        for path in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                     r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                    if winreg.QueryValueEx(k, "Installed")[0] == 1:
                        return True
            except OSError:
                continue
    except ImportError:
        pass
    return False


def run_elevated_wait(exe, args):
    quoted = ",".join("'" + a.replace("'", "''") + "'" for a in args)
    cmd = f"Start-Process -FilePath '{exe}' -ArgumentList {quoted} -Verb RunAs -Wait"
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], env=clean_child_env(),
                   creationflags=0x08000000 if IS_WIN else 0)


def ps3_firmware_installed(folder: Path):
    return (folder / "dev_flash" / "vsh" / "module" / "vsh.self").exists()


def latest_ps3_firmware_url():
    txt = http_get(PS3_UPDATE_LIST).read().decode("utf-8", "replace")
    m = re.search(r"CDN=(https?://[^;\s]+PS3UPDAT\.PUP)", txt)
    if not m:
        raise RuntimeError("couldn't read Sony's PS3 update list")
    ver = re.search(r"SystemSoftwareVersion=([\d.]+)", txt)
    return m.group(1), (ver.group(1) if ver else "?")


class InstallWorker(QThread):
    log = Signal(str)
    step = Signal(int, int, str)          # index, total, label
    bytes = Signal(int, int)              # got, total for current download
    installed = Signal(str, str)          # key, version
    all_done = Signal()

    def __init__(self, keys, versions, force=False):
        super().__init__()
        self.keys, self.versions, self.force = keys, dict(versions), force
        self.stop = False
        self.did_vc = False
        self.failed = []

    def tmp(self):
        d = Path(tempfile.mkdtemp(prefix="cv_"))
        return d

    def run(self):
        for i, key in enumerate(self.keys):
            if self.stop:
                break
            e = EMULATORS[key]
            self.step.emit(i, len(self.keys), e["name"])
            dest = EMU_DIR / key
            try:
                info = resolve_latest(key)
                have = find_exe_in(dest, folder_exes(key))
                if have and self.versions.get(key) == info["version"] and not self.force:
                    self.log.emit(f"✔ {e['name']} is already up to date ({info['version']})")
                else:
                    self.log.emit(f"⬇ {e['name']} {info['version']}  —  {info['name']}")
                    work = self.tmp()
                    try:
                        arc = work / info["name"]
                        download_file(info["url"], arc, lambda g, t: self.bytes.emit(g, t), lambda: self.stop)
                        self.log.emit("   extracting…")
                        extract_archive(arc, work / "x")
                        merge_tree(work / "x", dest)
                    finally:
                        shutil.rmtree(work, ignore_errors=True)
                    for f in e.get("portable_files", []):
                        (dest / f).touch(exist_ok=True)
                    for d in e.get("portable_dirs", []):
                        (dest / d).mkdir(exist_ok=True)
                    for note in dest.glob("PUT_*_HERE.txt"):
                        note.unlink(missing_ok=True)
                    if not find_exe_in(dest, folder_exes(key)):
                        raise RuntimeError("downloaded, but its .exe wasn't where expected")
                    self.installed.emit(key, info["version"])
                    self.log.emit(f"✔ {e['name']} installed")
                for need in e.get("needs", []):
                    self.handle_need(need, key, dest)
            except Exception as ex:
                self.log.emit(f"✖ {e['name']}: {ex}")
                self.failed.append(key)
        self.all_done.emit()

    def handle_need(self, need, key, dest):
        if need == "vcredist":
            if self.did_vc or vcredist_installed():
                return
            self.did_vc = True
            self.log.emit("⬇ Microsoft Visual C++ runtime (Windows will ask for permission)…")
            work = self.tmp()
            try:
                exe = download_file(VCREDIST_URL, work / "vc_redist.x64.exe", lambda g, t: self.bytes.emit(g, t))
                run_elevated_wait(str(exe), ["/install", "/quiet", "/norestart"])
                self.log.emit("✔ Visual C++ runtime installed" if vcredist_installed()
                              else "⚠ Visual C++ runtime may not have installed (permission declined?)")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        elif need == "ps3fw":
            if ps3_firmware_installed(dest):
                self.log.emit("✔ PS3 firmware already installed")
                return
            url, ver = latest_ps3_firmware_url()
            self.log.emit(f"⬇ PS3 system software {ver} from Sony…")
            work = self.tmp()
            try:
                pup = download_file(url, work / "PS3UPDAT.PUP", lambda g, t: self.bytes.emit(g, t),
                                    lambda: self.stop)
                exe = find_exe_in(dest, folder_exes(key))
                self.log.emit("   installing into RPCS3 (an RPCS3 window will pop up — let it finish)…")
                subprocess.run([str(exe), "--installfw", str(pup)], cwd=str(exe.parent), env=clean_child_env(),
                               timeout=1800)
                self.log.emit("✔ PS3 firmware installed" if ps3_firmware_installed(dest)
                              else "⚠ Firmware install didn't finish — in RPCS3 use File > Install Firmware")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        elif need == "xemuhdd":
            if any(dest.glob("*.qcow2")):
                return
            self.log.emit("⬇ xemu blank hard-drive image…")
            work = self.tmp()
            try:
                z = download_file(XEMU_HDD_URL, work / "hdd.zip", lambda g, t: self.bytes.emit(g, t))
                extract_archive(z, dest)
                self.log.emit("✔ Xbox HDD image ready (still needs your MCPX + BIOS dumps)")
            finally:
                shutil.rmtree(work, ignore_errors=True)


class VersionCheckWorker(QThread):
    result = Signal(str, str)   # key, latest version (or "error: ...")
    all_done = Signal()

    def __init__(self, keys):
        super().__init__()
        self.keys = keys

    def run(self):
        for k in self.keys:
            try:
                self.result.emit(k, resolve_latest(k)["version"])
            except Exception as ex:
                self.result.emit(k, f"error: {ex}")
        self.all_done.emit()


def search_roots():
    env = os.environ.get
    home = Path.home()
    roots = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        if env(var):
            roots.append((Path(env(var)), 3))
    if env("LOCALAPPDATA"):
        roots += [(Path(env("LOCALAPPDATA")) / "Programs", 3), (Path(env("LOCALAPPDATA")), 2)]
    if env("APPDATA"):
        roots.append((Path(env("APPDATA")), 2))
    for sub in ("Desktop", "Downloads", "Documents", "OneDrive", "Games", "Emulators"):
        roots.append((home / sub, 4))
    roots += [(home / "scoop" / "apps", 3), (home, 2)]
    if IS_WIN:
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for base in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                    try:
                        with winreg.OpenKey(hive, base) as k:
                            for i in range(winreg.QueryInfoKey(k)[0]):
                                try:
                                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                                        loc = winreg.QueryValueEx(sk, "InstallLocation")[0]
                                        if loc:
                                            roots.append((Path(loc), 2))
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except ImportError:
            pass
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append((drive, 3))
    seen, out = set(), []
    for p, d in roots:
        key = os.path.normcase(str(p))
        if key not in seen and p.exists():
            seen.add(key)
            out.append((p, d))
    return out


SKIP_DIRS = {"windows", "$recycle.bin", "system volume information", "winsxs", "node_modules", ".git",
             "microsoft", "packages", "temp", "cache", "programdata", "appdata", "steamapps", "windowsapps"}


class DetectWorker(QThread):
    found = Signal(dict)  # key -> [paths]
    log = Signal(str)

    def run(self):
        targets = {}
        for s in SYSTEMS:
            for x in s["exes"]:
                targets.setdefault(x.lower(), s["folder"])
        lib = os.path.normcase(str(EMU_DIR))
        res = {}
        seen = set()
        deadline = QTimerClock.now() + 120_000

        def walk(d, depth):
            if QTimerClock.now() > deadline:
                return
            dn = os.path.normcase(str(d))
            if dn in seen or dn.startswith(lib):
                return
            seen.add(dn)
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError:
                return
            for en in entries:
                try:
                    if en.is_file(follow_symlinks=False):
                        k = targets.get(en.name.lower())
                        if k:
                            res.setdefault(k, [])
                            if en.path not in res[k]:
                                res[k].append(en.path)
                    elif depth > 0 and en.is_dir(follow_symlinks=False) and en.name.lower() not in SKIP_DIRS:
                        walk(Path(en.path), depth - 1)
                except OSError:
                    pass

        for root, depth in search_roots():
            self.log.emit(f"Searching {root}…")
            walk(root, depth)
        self.found.emit(res)


def import_bios_folder(src: Path):
    """Copy the user's own BIOS/key dumps into each emulator's folder. Returns list of messages."""
    msgs = []
    for root, dirs, files in os.walk(src):
        if len(Path(root).relative_to(src).parts) >= 3:
            dirs[:] = []
        for f in files:
            p = Path(root) / f
            name = f.lower()
            try:
                size = p.stat().st_size
            except OSError:
                continue
            for pat, need_size, emu, sub in BIOS_RULES:
                if re.search(pat, name) and (need_size is None or size == need_size):
                    dest = EMU_DIR / emu / sub
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest / f)
                    msgs.append(f"✔ {f} → {EMULATORS[emu]['name']}")
                    break
    return msgs


class SetupDialog(QDialog):
    """Auto-detect, auto-install/update emulators, and import BIOS files."""

    def __init__(self, main, preselect=None, autostart=False):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(f"{APP_NAME} — Setup & Auto-Install")
        self.resize(1000, 700)
        self.worker = None
        lay = QVBoxLayout(self)

        intro = QLabel("Tick the emulators you want, then <b>Install / Update</b>. ConsoleVault downloads the "
                       "latest stable version of each, sets it up in portable mode, and grabs official extras "
                       "(PS3 firmware from Sony, Visual C++ runtime, xemu HDD image).<br>"
                       "<span style='color:#9aa3b8'>BIOS files and keys aren't downloadable — dump them from your "
                       "own consoles and use <b>Import my BIOS / keys</b>.</span>")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Emulator", "Consoles", "Status", "Latest", "Still needs"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.rows = {}
        for key, e in EMULATORS.items():
            consoles = ", ".join(s["short"] for s in SYSTEMS if s["folder"] == key)
            it = QTreeWidgetItem([e["name"], consoles, "", "", BIOS_NOTES.get(key, "nothing")])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setData(0, Qt.UserRole, key)
            self.tree.addTopLevelItem(it)
            self.rows[key] = it
        for c, w in enumerate((150, 190, 300, 130)):
            self.tree.setColumnWidth(c, w)
        lay.addWidget(self.tree, 1)

        r1 = QHBoxLayout()
        self.b_all = QPushButton("Select all")
        self.b_all.clicked.connect(lambda: self.set_all(True))
        self.b_none = QPushButton("Select none")
        self.b_none.clicked.connect(lambda: self.set_all(False))
        self.b_detect = QPushButton("🔍  Detect emulators already on this PC")
        self.b_detect.clicked.connect(self.detect)
        self.b_check = QPushButton("↻  Check for updates")
        self.b_check.clicked.connect(self.check_versions)
        for b in (self.b_all, self.b_none, self.b_detect, self.b_check):
            r1.addWidget(b)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        self.b_install = QPushButton("⬇  Install / Update selected")
        self.b_install.setObjectName("play")
        self.b_install.clicked.connect(self.install)
        self.b_bios = QPushButton("🔑  Import my BIOS / keys…")
        self.b_bios.clicked.connect(self.import_bios)
        self.b_cancel = QPushButton("Stop")
        self.b_cancel.clicked.connect(self.cancel)
        self.b_cancel.setEnabled(False)
        r2.addWidget(self.b_install, 2)
        r2.addWidget(self.b_bios, 1)
        r2.addWidget(self.b_cancel)
        lay.addLayout(r2)

        self.status = QLabel("")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setFixedHeight(170)
        lay.addWidget(self.logbox)

        self.refresh_rows()
        for key, it in self.rows.items():
            if preselect is None:
                on = not self.status_of(key)[1]
            else:
                on = key in ([preselect] if isinstance(preselect, str) else preselect)
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        if autostart:
            QTimer.singleShot(200, self.install)
        else:
            QTimer.singleShot(200, self.check_versions)

    # ---- helpers
    def versions(self):
        return self.main.cfg.data.setdefault("emulators", {})

    def status_of(self, key):
        lib_exe = find_exe_in(EMU_DIR / key, folder_exes(key))
        if lib_exe:
            v = self.versions().get(key, {}).get("version")
            return (f"Installed{(' — ' + v) if v else ''}", True)
        for s in SYSTEMS:
            if s["folder"] == key:
                p = self.main.cfg.sys(s["id"]).get("exe")
                if p and Path(p).exists():
                    return (f"Using {p}", True)
        return ("Not installed", False)

    def refresh_rows(self):
        for key, it in self.rows.items():
            text, ok = self.status_of(key)
            it.setText(2, text)
            it.setForeground(2, QColor("#66bb6a" if ok else "#9aa3b8"))

    def set_all(self, on):
        for it in self.rows.values():
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def selected(self):
        return [k for k, it in self.rows.items() if it.checkState(0) == Qt.Checked]

    def log(self, text):
        self.logbox.appendPlainText(text)

    def busy(self, on):
        for b in (self.b_install, self.b_detect, self.b_check, self.b_bios, self.b_all, self.b_none):
            b.setEnabled(not on)
        self.b_cancel.setEnabled(on)

    # ---- version check
    def check_versions(self):
        if self.worker and self.worker.isRunning():
            return
        self.status.setText("Checking latest versions…")
        self.vworker = VersionCheckWorker(list(EMULATORS))
        self.vworker.result.connect(self.on_version)
        self.vworker.all_done.connect(lambda: self.status.setText("Latest versions checked."))
        self.vworker.start()

    def on_version(self, key, latest):
        it = self.rows[key]
        if latest.startswith("error"):
            it.setText(3, "unavailable")
            it.setToolTip(3, latest)
            return
        it.setText(3, latest)
        cur = self.versions().get(key, {}).get("version")
        lib_exe = find_exe_in(EMU_DIR / key, folder_exes(key))
        if lib_exe and cur and cur != latest:
            it.setText(2, f"Update available ({cur} → {latest})")
            it.setForeground(2, QColor("#ffb74d"))
            it.setCheckState(0, Qt.Checked)

    # ---- install
    def install(self):
        keys = self.selected()
        if not keys:
            return QMessageBox.information(self, APP_NAME, "Tick at least one emulator.")
        vers = {k: v.get("version") for k, v in self.versions().items()}
        self.worker = InstallWorker(keys, vers)
        self.worker.log.connect(self.log)
        self.worker.step.connect(lambda i, n, name: (self.status.setText(f"[{i + 1}/{n}]  {name}"),))
        self.worker.bytes.connect(self.on_bytes)
        self.worker.installed.connect(self.on_installed)
        self.worker.all_done.connect(self.on_done)
        self.busy(True)
        self.log(f"— Installing {len(keys)} emulator(s) into {EMU_DIR}")
        self.worker.start()

    def on_bytes(self, got, total):
        if total:
            self.bar.setMaximum(1000)
            self.bar.setValue(int(got * 1000 / total))
        else:
            self.bar.setMaximum(0)

    def on_installed(self, key, version):
        self.versions().setdefault(key, {})["version"] = version
        for s in SYSTEMS:  # an auto-installed copy replaces any old external path
            if s["folder"] == key:
                self.main.cfg.sys(s["id"]).pop("exe", None)
        self.main.cfg.save()
        self.refresh_rows()

    def on_done(self):
        self.busy(False)
        self.bar.setMaximum(1000)
        self.bar.setValue(1000)
        self.status.setText("All done.")
        self.log("— Finished.")
        self.refresh_rows()
        self.main.refresh()
        failed = [k for k in self.worker.failed if k in EMULATORS]
        if failed and not self.worker.stop:
            names = ", ".join(EMULATORS[k]["name"] for k in failed)
            if QMessageBox.question(self, APP_NAME, f"Couldn't download automatically: {names}\n\n"
                                    "Open their official download pages? Unzip each one into the folder "
                                    "that opens and ConsoleVault will pick it up.") == QMessageBox.Yes:
                for k in failed:
                    url = next((s["url"] for s in SYSTEMS if s["folder"] == k), None)
                    if url:
                        webbrowser.open(url)
                    open_path(EMU_DIR / k)

    def cancel(self):
        if self.worker:
            self.worker.stop = True
            self.log("Stopping after the current step…")

    # ---- detect
    def detect(self):
        self.busy(True)
        self.status.setText("Searching this PC for emulators (up to 2 minutes)…")
        self.bar.setMaximum(0)
        self.dworker = DetectWorker()
        self.dworker.log.connect(self.status.setText)
        self.dworker.found.connect(self.on_detected)
        self.dworker.start()

    def on_detected(self, found):
        self.busy(False)
        self.bar.setMaximum(1000)
        self.bar.setValue(1000)
        if not found:
            self.status.setText("No existing emulators found.")
            self.log("🔍 No emulators found outside your library.")
            return
        lines = []
        for key, paths in found.items():
            lines.append(f"{EMULATORS[key]['name']}:  {paths[0]}")
            self.log(f"🔍 Found {EMULATORS[key]['name']}: {paths[0]}" +
                     (f"  (+{len(paths) - 1} more)" if len(paths) > 1 else ""))
        ans = QMessageBox.question(self, APP_NAME, "Found these emulators already on your PC:\n\n" +
                                   "\n".join(lines) + "\n\nUse them instead of downloading new copies?")
        if ans == QMessageBox.Yes:
            for key, paths in found.items():
                for s in SYSTEMS:
                    if s["folder"] == key:
                        self.main.cfg.sys(s["id"])["exe"] = paths[0]
                self.rows[key].setCheckState(0, Qt.Unchecked)
            self.main.cfg.save()
            self.refresh_rows()
            self.main.refresh()
        self.status.setText(f"Found {len(found)} emulator(s).")

    # ---- BIOS
    def import_bios(self):
        d = QFileDialog.getExistingDirectory(self, "Pick the folder with your BIOS / key dumps", str(Path.home()))
        if not d:
            return
        msgs = import_bios_folder(Path(d))
        for m in msgs or ["No recognised BIOS or key files in that folder."]:
            self.log(m)
        if msgs and any("xemu" in m.lower() or "xbox" in m.lower() for m in msgs):
            self.log("   xemu: point Settings > System at the files in emulators\\xemu\\bios once.")

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, APP_NAME, "Installs are still running. Stop them?") != QMessageBox.Yes:
                return ev.ignore()
            self.worker.stop = True
            self.worker.wait(5000)
        super().closeEvent(ev)


class EmulatorUpdateCheck(QThread):
    """Background check for newer versions of emulators ConsoleVault installed."""
    found = Signal(list)

    def __init__(self, versions):
        super().__init__()
        self.versions = versions

    def run(self):
        out = []
        for key, v in self.versions.items():
            if key in EMULATORS and v.get("version") and find_exe_in(EMU_DIR / key, folder_exes(key)):
                try:
                    if resolve_latest(key)["version"] != v["version"]:
                        out.append(key)
                except Exception:
                    pass
        self.found.emit(out)


def selftest_sources(download=False):
    """CLI check used by the GitHub build: can every emulator still be found / downloaded?"""
    import time
    set_library(Path(tempfile.mkdtemp(prefix="cvtest_")))
    bad = 0
    for key, e in EMULATORS.items():
        try:
            info = resolve_latest(key)
            print(f"OK   {e['name']:<14} {info['version']:<22} {info['url']}", flush=True)
            if download:
                work = Path(tempfile.mkdtemp())
                arc = download_file(info["url"], work / info["name"])
                extract_archive(arc, work / "x")
                merge_tree(work / "x", EMU_DIR / key)
                exe = find_exe_in(EMU_DIR / key, folder_exes(key))
                print(f"     extracted -> exe {'FOUND ' + exe.name if exe else 'MISSING: ' + str(folder_exes(key))}",
                      flush=True)
                if not exe:
                    bad += 1
                    print("     files:", [p.name for p in (EMU_DIR / key).iterdir()][:25], flush=True)
                shutil.rmtree(work, ignore_errors=True)
        except Exception as ex:
            bad += 1
            print(f"FAIL {e['name']:<14} {ex}", flush=True)
        time.sleep(0.3)
    try:
        url, ver = latest_ps3_firmware_url()
        print(f"OK   PS3 firmware   {ver:<22} {url}")
    except Exception as ex:
        bad += 1
        print(f"FAIL PS3 firmware   {ex}")
    print(f"\n{bad} problem(s)")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class Config:
    def __init__(self):
        self.data = {"systems": {}, "custom_systems": [], "last": None}
        if CFG_PATH.exists():
            try:
                self.data.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        try:
            CFG_PATH.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def sys(self, sid):
        return self.data["systems"].setdefault(sid, {})


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, parent, s, cfg, exe, args, romdir):
        super().__init__(parent)
        self.setWindowTitle(f"{s['short']} settings")
        self.setMinimumWidth(640)
        self.s, self.cfg = s, cfg
        lay = QFormLayout(self)

        self.exe = QLineEdit(str(exe) if exe else "")
        b1 = QPushButton("Browse…")
        b1.clicked.connect(self.pick_exe)
        r1 = QHBoxLayout(); r1.addWidget(self.exe); r1.addWidget(b1)
        lay.addRow("Emulator .exe", r1)

        self.args = QLineEdit(subprocess.list2cmdline(args) if IS_WIN else shlex.join(args))
        lay.addRow("Launch arguments", self.args)
        lay.addRow("", QLabel("{rom} = the game file. Leave as-is unless you know you need something different."))

        self.rom = QLineEdit(str(romdir))
        b2 = QPushButton("Browse…")
        b2.clicked.connect(self.pick_rom)
        r2 = QHBoxLayout(); r2.addWidget(self.rom); r2.addWidget(b2)
        lay.addRow("Games folder", r2)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.defaults)
        lay.addRow(bb)

    def pick_exe(self):
        f, _ = QFileDialog.getOpenFileName(self, "Pick emulator exe", str(EMU_DIR / self.s["folder"]), "Programs (*.exe);;All files (*)")
        if f:
            self.exe.setText(f)

    def pick_rom(self):
        d = QFileDialog.getExistingDirectory(self, "Pick games folder", self.rom.text())
        if d:
            self.rom.setText(d)

    def defaults(self):
        self.cfg.data["systems"].pop(self.s["id"], None)
        self.cfg.save()
        self.accept()

    def save(self):
        c = self.cfg.sys(self.s["id"])
        exe = self.exe.text().strip()
        auto = detect_exe(self.s)
        c["exe"] = exe if exe and (not auto or Path(exe) != auto) else None
        try:
            parsed = shlex.split(self.args.text(), posix=not IS_WIN)
            parsed = [a.strip('"') for a in parsed]
        except ValueError:
            parsed = self.s["args"]
        c["args"] = None if parsed == self.s["args"] else parsed
        rom = self.rom.text().strip()
        c["rom_dir"] = None if not rom or Path(rom) == ROM_DIR / self.s["id"] else rom
        self.cfg.save()
        self.accept()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
STYLE = """
QWidget { background:#10131a; color:#e8eaf2; font-family:'Segoe UI'; font-size:15px; }
QListWidget { background:#161a24; border:none; outline:0; }
QListWidget::item { padding:12px 14px; border-radius:10px; margin:2px 8px; }
QListWidget::item:selected { background:#2c3550; color:#ffffff; }
QListWidget::item:hover { background:#1f2533; }
QListWidget#games { background:#13161f; font-size:18px; }
QPushButton { background:#222838; border:1px solid #2e3650; border-radius:10px; padding:11px 14px; }
QPushButton:hover, QPushButton:focus { background:#2d3651; border-color:#5b7cff; }
QPushButton#play { background:#2e7d32; border-color:#4caf50; font-weight:700; }
QPushButton#play:hover, QPushButton#play:focus { background:#388e3c; }
QPushButton:disabled { color:#5c6273; background:#171a23; border-color:#20242f; }
QLineEdit { background:#1a1e2a; border:1px solid #2e3650; border-radius:10px; padding:9px 12px; }
QLabel#title { font-size:32px; font-weight:800; }
QLabel#sub { color:#9aa3b8; font-size:14px; }
QLabel#empty { color:#7d869c; font-size:17px; }
QLabel#hint { color:#5f6880; font-size:12px; }
QScrollBar:vertical { background:transparent; width:8px; margin:4px 2px; }
QScrollBar::handle:vertical { background:#2e3650; border-radius:3px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
"""


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.cfg = Config()
        self.systems = SYSTEMS + [c for c in self.cfg.data.get("custom_systems", []) if "id" in c]
        self.ensure_dirs()
        self.cur = None
        self.embed = None  # dict(proc, win, container, hwnd)
        self.setAcceptDrops(True)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Left: console list
        left = QWidget()
        left.setFixedWidth(300)
        left.setStyleSheet("background:#161a24;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 18, 0, 10)
        logo = QLabel("  🎮  ConsoleVault")
        logo.setStyleSheet("font-size:24px;font-weight:800;padding:4px 14px 14px;")
        lv.addWidget(logo)
        self.consoles = QListWidget()
        self.consoles.setObjectName("consoles")
        self.consoles.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        lv.addWidget(self.consoles)
        hint = QLabel("  ↑↓ consoles · → games · Enter play · F11 fullscreen")
        hint.setObjectName("hint")
        lv.addWidget(hint)
        setupb = QPushButton("⚡  Setup && Auto-Install")
        setupb.setStyleSheet("margin:4px 10px;padding:9px;")
        setupb.clicked.connect(lambda: self.open_setup())
        lv.addWidget(setupb)
        foot = QHBoxLayout()
        ver = QLabel(f"  v{VERSION}" if "__" not in VERSION else "  dev build")
        ver.setObjectName("hint")
        foot.addWidget(ver, 1)
        libb = QPushButton("📚 Library…")
        libb.setStyleSheet("padding:4px 10px;font-size:12px;")
        libb.setToolTip(f"Library: {BASE}")
        libb.clicked.connect(self.change_library)
        foot.addWidget(libb)
        foot.setContentsMargins(0, 0, 10, 0)
        lv.addLayout(foot)
        h.addWidget(left)

        # Right: detail panel
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(28, 22, 28, 18)
        rv.setSpacing(12)
        self.update_bar = QWidget()
        self.update_bar.setStyleSheet("background:#1d3b2a;border-radius:10px;")
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(14, 8, 8, 8)
        self.update_label = QLabel()
        self.update_label.setStyleSheet("background:transparent;font-weight:600;")
        ub.addWidget(self.update_label, 1)
        self.b_update = self.btn("⬆  Update now", self.install_update, "play")
        ub.addWidget(self.b_update)
        later = self.btn("Later", self.update_bar.hide)
        ub.addWidget(later)
        self.update_bar.hide()
        rv.addWidget(self.update_bar)
        self.emu_bar = QWidget()
        self.emu_bar.setStyleSheet("background:#3b2f1d;border-radius:10px;")
        eb = QHBoxLayout(self.emu_bar)
        eb.setContentsMargins(14, 8, 8, 8)
        self.emu_label = QLabel()
        self.emu_label.setStyleSheet("background:transparent;font-weight:600;")
        eb.addWidget(self.emu_label, 1)
        eb.addWidget(self.btn("⬆  Update emulators", lambda: (self.emu_bar.hide(),
                              self.open_setup(preselect=self.emu_update_keys, autostart=True)), "play"))
        eb.addWidget(self.btn("Later", self.emu_bar.hide))
        self.emu_bar.hide()
        self.emu_update_keys = []
        rv.addWidget(self.emu_bar)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.sub = QLabel()
        self.sub.setObjectName("sub")
        self.sub.setWordWrap(True)
        rv.addWidget(self.title)
        rv.addWidget(self.sub)

        g = QGridLayout()
        g.setSpacing(10)
        self.b_play = self.btn("▶  Play Game", self.play_selected, "play")
        self.b_emu = self.btn("⧉  Open Emulator", self.open_emulator)
        self.b_inside = self.btn("▣  Open Inside ConsoleVault", self.open_inside)
        self.b_set = self.btn("⚙  Settings", self.open_settings)
        self.b_add = self.btn("＋  Add Games", self.add_games)
        self.b_addf = self.btn("＋  Add Game Folder", self.add_game_folder)
        self.b_roms = self.btn("📁  Games Folder", lambda: open_path(self.romdir(self.cur)))
        self.b_emudir = self.btn("📁  Emulator Folder", lambda: open_path(EMU_DIR / self.cur["folder"]))
        self.b_get = self.btn("⬇  Install Emulator", self.get_emulator)
        for i, b in enumerate([self.b_play, self.b_emu, self.b_inside, self.b_set, self.b_get]):
            g.addWidget(b, 0, i)
        for i, b in enumerate([self.b_add, self.b_addf, self.b_roms, self.b_emudir]):
            g.addWidget(b, 1, i)
        rv.addLayout(g)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games…  (Ctrl+F)")
        self.search.textChanged.connect(self.filter_games)
        rv.addWidget(self.search)

        self.stack = QStackedWidget()
        self.games = QListWidget()
        self.games.setObjectName("games")
        self.games.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.games.itemActivated.connect(lambda _i: self.play_selected())
        self.stack.addWidget(self.games)                    # 0
        self.empty = QLabel()
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)                    # 1
        self.embed_page = QWidget()
        ev = QVBoxLayout(self.embed_page)
        ev.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.embed_label = QLabel()
        bar.addWidget(self.embed_label, 1)
        bar.addWidget(self.btn("⇱  Pop Out", self.pop_out))
        bar.addWidget(self.btn("✕  Close Emulator", self.close_embedded))
        ev.addLayout(bar)
        self.embed_area = QWidget()
        self.embed_area.setStyleSheet("background:#000;")
        self.embed_lay = QVBoxLayout(self.embed_area)
        self.embed_lay.setContentsMargins(0, 0, 0, 0)
        ev.addWidget(self.embed_area, 1)
        self.stack.addWidget(self.embed_page)               # 2
        rv.addWidget(self.stack, 1)
        h.addWidget(right, 1)
        self.setCentralWidget(root)

        for s in self.systems:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, s["id"])
            self.consoles.addItem(it)
        self.consoles.currentRowChanged.connect(self.select_row)
        self.consoles.installEventFilter(self)
        self.games.installEventFilter(self)

        QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("F5"), self, self.refresh)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)

        self.embed_timer = QTimer(self)
        self.embed_timer.timeout.connect(self.poll_embed)
        self.pad = Gamepad(self.on_pad)

        if not any(self.exe(s) for s in self.systems) and not self.cfg.data.get("setup_offered"):
            self.cfg.data["setup_offered"] = True
            self.cfg.save()
            QTimer.singleShot(600, lambda: self.open_setup())
        QTimer.singleShot(4000, self.check_emulator_updates)

        self.pending_update = None
        self.auto_install = True   # first check right after launch installs straight away
        if updates_enabled():
            self.update_timer = QTimer(self)
            self.update_timer.timeout.connect(self.check_updates)
            self.update_timer.start(6 * 60 * 60 * 1000)  # and every 6 hours
            QTimer.singleShot(1500, self.check_updates)

        self.refresh_console_labels()
        ids = [s["id"] for s in self.systems]
        last = self.cfg.data.get("last")
        self.consoles.setCurrentRow(ids.index(last) if last in ids else 0)
        self.consoles.setFocus()

    # ---- small helpers -------------------------------------------------
    def btn(self, text, fn, name=None):
        b = QPushButton(text)
        if name:
            b.setObjectName(name)
        b.clicked.connect(fn)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def ensure_dirs(self):
        for s in self.systems:
            ed = EMU_DIR / s["folder"]
            ed.mkdir(parents=True, exist_ok=True)
            note = ed / f"PUT_{s['emu'].split()[0].upper()}_HERE.txt"
            if not note.exists() and not any(ed.glob("*.exe")):
                try:
                    note.write_text(f"Download {s['emu']} from {s['url']}\n"
                                    f"Unzip it into this folder so its .exe sits here "
                                    f"(or in a subfolder). ConsoleVault will find it automatically.\n")
                except OSError:
                    pass
            self.romdir(s).mkdir(parents=True, exist_ok=True)

    def exe(self, s):
        p = self.cfg.sys(s["id"]).get("exe")
        if p and Path(p).exists():
            return Path(p)
        return detect_exe(s)

    def args(self, s):
        a = self.cfg.sys(s["id"]).get("args")
        return a if a is not None else s["args"]

    def romdir(self, s):
        r = self.cfg.sys(s["id"]).get("rom_dir")
        return Path(r) if r else ROM_DIR / s["id"]

    # ---- console list --------------------------------------------------
    def refresh_console_labels(self):
        for i, s in enumerate(self.systems):
            ok = self.exe(s) is not None
            self.consoles.item(i).setText(f"{'🟢' if ok else '⚪'}  {s['short']}\n       {s['emu']}")

    def select_row(self, row):
        if row < 0:
            return
        if self.embed:
            self.pop_out()
        self.cur = self.systems[row]
        self.cfg.data["last"] = self.cur["id"]
        self.cfg.save()
        self.search.clear()
        self.refresh()

    def refresh(self):
        s = self.cur
        if not s:
            return
        exe = self.exe(s)
        color = s.get("color", "#5b7cff")
        self.title.setText(s["name"])
        self.title.setStyleSheet(f"color:{color};")
        status = (f"<span style='color:#66bb6a'>✔ {s['emu']} ready</span> — {exe}" if exe else
                  f"<span style='color:#ef5350'>✖ {s['emu']} not installed</span> — click <b>Get Emulator</b>, "
                  f"then unzip it into the folder that opens.")
        note = f"<br>{s['note']}" if s.get("note") else ""
        self.sub.setText(f"{status}<br>Games folder: {self.romdir(s)}{note}")
        for b in (self.b_play, self.b_emu, self.b_inside):
            b.setEnabled(exe is not None)
        self.b_inside.setVisible(HAS_CT)

        self.games.clear()
        for name, path in scan_games(s, self.romdir(s)):
            it = QListWidgetItem(f"  {name}")
            it.setData(Qt.UserRole, str(path))
            it.setToolTip(str(path))
            self.games.addItem(it)
        if self.embed:
            self.stack.setCurrentIndex(2)
        elif self.games.count():
            self.stack.setCurrentIndex(0)
            self.games.setCurrentRow(0)
        else:
            self.empty.setText(f"No {s['short']} games yet.\n\nClick “Add Games”, drag files onto this window,\n"
                               f"or drop them into:\n{self.romdir(s)}")
            self.stack.setCurrentIndex(1)
        self.refresh_console_labels()

    def filter_games(self, text):
        t = text.lower().strip()
        first = None
        for i in range(self.games.count()):
            it = self.games.item(i)
            hide = bool(t) and t not in it.text().lower()
            it.setHidden(hide)
            if not hide and first is None:
                first = i
        if first is not None:
            self.games.setCurrentRow(first)

    # ---- launching -----------------------------------------------------
    def launch(self, cmd, exe):
        env = clean_child_env()
        reset_dll_dir = HAS_CT and hasattr(sys, "_MEIPASS")
        try:
            if reset_dll_dir:  # don't let the emulator load OUR bundled DLLs (msvcp140, Qt, ...)
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            flags = 0x00000200 if IS_WIN else 0  # CREATE_NEW_PROCESS_GROUP
            return subprocess.Popen(cmd, cwd=str(exe.parent), env=env, creationflags=flags)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't start {exe.name}\n\n{e}")
            return None
        finally:
            if reset_dll_dir:
                ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)

    def play_selected(self):
        s = self.cur
        exe = self.exe(s)
        if not exe:
            return self.get_emulator()
        args = self.args(s)
        if not any("{rom}" in a for a in args):
            return self.open_emulator()
        it = self.games.currentItem()
        if not it or it.isHidden():
            QMessageBox.information(self, APP_NAME, "Pick a game first.")
            return
        rom = it.data(Qt.UserRole)
        cmd = [str(exe)] + [a.replace("{rom}", rom) for a in args]
        self.launch(cmd, exe)

    def open_emulator(self):
        exe = self.exe(self.cur)
        if exe:
            self.launch([str(exe)], exe)

    # ---- embedding -----------------------------------------------------
    def open_inside(self):
        if not HAS_CT:
            return self.open_emulator()
        if self.embed:
            self.pop_out()
        exe = self.exe(self.cur)
        proc = self.launch([str(exe)], exe) if exe else None
        if not proc:
            return
        self.embed = dict(proc=proc, win=None, container=None, hwnd=None, tries=0)
        self.embed_label.setText(f"Starting {self.cur['emu']}…")
        self.stack.setCurrentIndex(2)
        self.embed_timer.start(300)

    def poll_embed(self):
        e = self.embed
        if not e:
            return self.embed_timer.stop()
        if e["proc"].poll() is not None:
            self.embed_timer.stop()
            self.clear_embed()
            return
        if e["hwnd"]:
            return  # attached; just watching for exit
        e["tries"] += 1
        hwnd = find_window_for_pid(e["proc"].pid)
        if hwnd:
            e["hwnd"] = hwnd
            QTimer.singleShot(800, self.attach_embed)
        elif e["tries"] > 60:
            self.embed_timer.stop()
            self.embed = None
            self.refresh()
            QMessageBox.information(self, APP_NAME, f"{self.cur['emu']} opened in its own window "
                                                    f"(it couldn't be captured inside ConsoleVault).")

    def attach_embed(self):
        e = self.embed
        if not e or not e["hwnd"]:
            return
        win = QWindow.fromWinId(int(e["hwnd"]))
        cont = QWidget.createWindowContainer(win, self.embed_area)
        cont.setFocusPolicy(Qt.StrongFocus)
        self.embed_lay.addWidget(cont)
        e["win"], e["container"] = win, cont
        self.embed_label.setText(f"{self.cur['emu']} running inside ConsoleVault — games open in their own window")
        cont.setFocus()

    def detach_embed(self):
        e = self.embed
        if e and e["win"]:
            e["win"].setParent(None)
            e["container"].setParent(None)
            e["container"].deleteLater()
            restore_toplevel(e["hwnd"])

    def clear_embed(self):
        e, self.embed = self.embed, None
        if e and e["container"]:
            e["container"].setParent(None)
            e["container"].deleteLater()
        self.refresh()

    def pop_out(self):
        if not self.embed:
            return
        self.embed_timer.stop()
        self.detach_embed()
        self.embed = None
        self.refresh()

    def close_embedded(self):
        if not self.embed:
            return
        self.embed_timer.stop()
        proc = self.embed["proc"]
        self.detach_embed()
        self.embed = None
        try:
            proc.terminate()
        except Exception:
            pass
        self.refresh()

    # ---- adding games --------------------------------------------------
    def add_games(self):
        s = self.cur
        pat = " ".join(f"*{e}" for e in s["ext"])
        files, _ = QFileDialog.getOpenFileNames(self, f"Add {s['short']} games", str(Path.home()),
                                                f"{s['short']} games ({pat});;All files (*)")
        if files:
            self.copy_in(files)

    def add_game_folder(self):
        d = QFileDialog.getExistingDirectory(self, f"Add a {self.cur['short']} game folder", str(Path.home()))
        if d:
            self.copy_in([d])

    def copy_in(self, paths):
        dest = self.romdir(self.cur)
        jobs = []
        for src in map(Path, paths):
            if src.is_file():
                jobs.append((src, dest / src.name))
            elif src.is_dir():
                jobs += [(f, dest / src.name / f.relative_to(src)) for f in src.rglob("*") if f.is_file()]
        jobs = [(a, b) for a, b in jobs if not (b.exists() and b.stat().st_size == a.stat().st_size)]
        if not jobs:
            return self.refresh()
        total = max(1, sum(a.stat().st_size for a, _ in jobs))
        dlg = QProgressDialog("Copying…", "Cancel", 0, 1000, self)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        done = 0
        for src, dst in jobs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dlg.setLabelText(f"Copying {src.name}")
            try:
                with open(src, "rb") as fi, open(dst, "wb") as fo:
                    while chunk := fi.read(8 * 1024 * 1024):
                        fo.write(chunk)
                        done += len(chunk)
                        dlg.setValue(int(done * 1000 / total))
                        QApplication.processEvents()
                        if dlg.wasCanceled():
                            break
                if dlg.wasCanceled():
                    dst.unlink(missing_ok=True)
                    break
                shutil.copystat(src, dst)
            except OSError as e:
                QMessageBox.warning(self, APP_NAME, f"Couldn't copy {src.name}\n{e}")
        dlg.setValue(1000)
        self.refresh()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.copy_in(paths)

    # ---- updates -------------------------------------------------------
    def check_updates(self):
        self.checker = UpdateChecker()
        self.checker.found.connect(self.on_update_found)
        self.checker.finished.connect(lambda: setattr(self, "auto_install", False))
        self.checker.start()

    def on_update_found(self, version, url):
        self.pending_update = (version, url)
        if self.auto_install:
            self.install_update()
        else:
            self.update_label.setText(f"ConsoleVault {version} is available")
            self.update_bar.show()

    def install_update(self):
        if not self.pending_update:
            return
        version, url = self.pending_update
        dest = str(Path(tempfile.gettempdir()) / f"ConsoleVault-Setup-{version}.exe")
        self.dl_dialog = QProgressDialog(f"Downloading ConsoleVault {version}…", "Cancel", 0, 100, self)
        self.dl_dialog.setWindowTitle(APP_NAME)
        self.dl_dialog.setWindowModality(Qt.WindowModal)
        self.dl_dialog.setMinimumDuration(0)
        self.dl = Downloader(url, dest)
        self.dl.progress.connect(lambda g, t: self.dl_dialog.setValue(int(g * 100 / t) if t else 0))
        self.dl.done.connect(self.run_installer)
        self.dl.failed.connect(lambda e: (self.dl_dialog.close(),
                                          QMessageBox.warning(self, APP_NAME, f"Update download failed:\n{e}")))
        self.dl_dialog.canceled.connect(self.dl.terminate)
        self.dl.start()

    def run_installer(self, path):
        self.dl_dialog.close()
        if self.dl_dialog.wasCanceled():
            return
        try:
            subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                             env=clean_child_env(), creationflags=0x00000008 | 0x00000200)
        except OSError as e:
            return QMessageBox.warning(self, APP_NAME, f"Couldn't start the updater:\n{e}")
        QApplication.quit()  # installer replaces the files and relaunches ConsoleVault

    def change_library(self):
        new = choose_library(self)
        if new and Path(new) != BASE:
            save_library(new)
            QProcess.startDetached(sys.executable, sys.argv[1:] if FROZEN else sys.argv)
            QApplication.quit()

    # ---- misc actions --------------------------------------------------
    def get_emulator(self):
        self.open_setup(preselect=self.cur["folder"], autostart=True)

    def open_setup(self, preselect=None, autostart=False):
        dlg = SetupDialog(self, preselect=preselect, autostart=autostart)
        dlg.exec()
        self.refresh()

    def check_emulator_updates(self):
        vers = self.cfg.data.get("emulators", {})
        if not vers:
            return
        self.emu_checker = EmulatorUpdateCheck(dict(vers))
        self.emu_checker.found.connect(self.on_emu_updates)
        self.emu_checker.start()

    def on_emu_updates(self, keys):
        if not keys:
            return
        self.emu_update_keys = keys
        names = ", ".join(EMULATORS[k]["name"] for k in keys)
        self.emu_label.setText(f"Emulator updates available: {names}")
        self.emu_bar.show()

    def open_settings(self):
        s = self.cur
        d = SettingsDialog(self, s, self.cfg, self.exe(s), self.args(s), self.romdir(s))
        if d.exec():
            self.romdir(s).mkdir(parents=True, exist_ok=True)
            self.refresh()

    def toggle_fullscreen(self):
        self.showMaximized() if self.isFullScreen() else self.showFullScreen()

    # ---- keyboard / controller navigation ------------------------------
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress:
            k = ev.key()
            if obj is self.consoles and k in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
                if self.stack.currentIndex() == 0:
                    self.games.setFocus()
                    if self.games.currentRow() < 0:
                        self.games.setCurrentRow(0)
                else:
                    self.b_add.setFocus()
                return True
            if obj is self.games:
                if k in (Qt.Key_Return, Qt.Key_Enter):
                    self.play_selected()
                    return True
                if k in (Qt.Key_Left, Qt.Key_Escape):
                    self.consoles.setFocus()
                    return True
        return super().eventFilter(obj, ev)

    def on_pad(self, name):
        if not self.isActiveWindow():
            return  # a game/emulator has focus - leave the controller alone
        keys = {"up": Qt.Key_Up, "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right,
                "a": Qt.Key_Return, "b": Qt.Key_Escape}
        if name in ("lb", "rb"):
            r = self.consoles.currentRow() + (1 if name == "rb" else -1)
            self.consoles.setCurrentRow(max(0, min(self.consoles.count() - 1, r)))
        elif name == "start":
            self.play_selected()
        elif name == "x":
            self.open_emulator()
        elif name == "y":
            self.open_inside()
        elif name == "back":
            self.toggle_fullscreen()
        elif name in keys:
            w = QApplication.focusWidget() or self.consoles
            if name == "a" and isinstance(w, QPushButton):
                return w.click()
            if name == "b" and w is not self.games:
                return self.consoles.setFocus()
            for t in (QEvent.KeyPress, QEvent.KeyRelease):
                QApplication.postEvent(w, QKeyEvent(t, keys[name], Qt.NoModifier))

    def changeEvent(self, ev):
        if ev.type() == QEvent.ActivationChange and self.isActiveWindow() and self.cur and not self.embed:
            QTimer.singleShot(0, self.rescan_keep_selection)  # pick up files added outside ConsoleVault
        super().changeEvent(ev)

    def rescan_keep_selection(self):
        cur = self.games.currentItem()
        keep = cur.data(Qt.UserRole) if cur else None
        had_focus = self.games.hasFocus()
        self.refresh()
        if keep:
            for i in range(self.games.count()):
                if self.games.item(i).data(Qt.UserRole) == keep:
                    self.games.setCurrentRow(i)
                    break
        if had_focus:
            self.games.setFocus()

    def closeEvent(self, ev):
        if self.embed:
            self.pop_out()
        super().closeEvent(ev)


def main():
    if "--check-sources" in sys.argv:
        sys.exit(selftest_sources(download="--download" in sys.argv))
    if HAS_CT:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 11))
    if not FROZEN or (APP_DIR / "portable.txt").exists():
        set_library(APP_DIR)            # running from source / portable mode: keep everything beside the exe
    else:
        lib = saved_library()
        if not lib:
            lib = choose_library(first_run=True)
            save_library(lib)
        set_library(lib)
    w = Main()
    w.resize(1400, 860)
    w.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
