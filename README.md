# ConsoleVault

All your emulators in one app. Install once, it updates itself.

## Using it
1. Download **ConsoleVault-Setup.exe** from this repo's **Releases** page and run it.
2. On first launch, pick where your emulators and games live. If you already
   have an `emulators` / `roms` folder from before, choose **Pick folder…** and select that folder.
3. The **Setup & Auto-Install** window opens: tick the emulators you want and click **Install / Update**.
   ConsoleVault downloads the latest stable version of each, sets it up in portable mode and grabs official
   extras (PS3 firmware from Sony, Visual C++ runtime, xemu HDD image). **Detect emulators already on this PC**
   reuses ones you already have. **Import my BIOS / keys** copies your own dumps into the right emulators.

ConsoleVault checks for a new version every time it starts (and every 6 hours).
When there's one, it downloads it, installs it silently and reopens itself.
Your emulators, games and settings are never touched by updates.

## Releasing an update
1. Change `consolevault.py`, and raise the number in `VERSION` (e.g. `1.0.0` → `1.0.1`).
2. Push / commit to `main`.
3. GitHub Actions builds `ConsoleVault-Setup.exe` (about 5 minutes) and publishes it as release `v1.0.1`.
   Every installed copy updates itself on its next launch. Pushes that don't change `VERSION` just build without releasing.

## Emulators
NES/SNES Mesen · GB/GBC/GBA mGBA · N64 RMG · DS melonDS · 3DS Azahar · GameCube/Wii Dolphin ·
Wii U Cemu · Switch Ryujinx · PS1 DuckStation · PS2 PCSX2 · PS3 RPCS3 · PSP PPSSPP ·
Vita Vita3K · Xbox xemu · Xbox 360 Xenia Canary · Dreamcast Flycast

## Controls
Keyboard: ↑↓ consoles, →/Enter games, Enter play, ←/Esc back, Ctrl+F search, F5 rescan, F11 fullscreen.
Xbox controller: D-pad/stick move, A select, B back, LB/RB switch console, Start play,
X open emulator, Y open inside, Back fullscreen.

## Notes
- PS1/PS2/PS3 and Switch need BIOS/firmware/keys from your own console, set up once inside each emulator.
- Portable mode: put an empty `portable.txt` next to `ConsoleVault.exe` to keep everything beside the exe.
- Extra consoles can be added under `"custom_systems"` in `consolevault_config.json`
  (same fields as the built-in list in `consolevault.py`).
