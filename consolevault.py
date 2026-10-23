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
import shlex
import shutil
import subprocess
import tempfile
import webbrowser
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QObject, QEvent, QThread, Signal, QProcess
from PySide6.QtGui import QFont, QKeyEvent, QWindow, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QStackedWidget, QLineEdit,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QProgressDialog, QAbstractItemView,
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
        self.b_get = self.btn("⬇  Get Emulator", self.get_emulator)
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
        webbrowser.open(self.cur["url"])
        open_path(EMU_DIR / self.cur["folder"])

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
