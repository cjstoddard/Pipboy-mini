# PipBoy Mini

A Fallout-style Pip-Boy interface for a Raspberry Pi Zero 2W, built around the Waveshare 1.44" LCD HAT. Four screens, joystick and button navigation, and an MP3 player — all on a 128×128 pixel display.

![Vault Boy](VaultBoy.png)

---

## Hardware

| Component | Notes |
|---|---|
| Raspberry Pi Zero 2W | Runs Raspbian GNU/Linux 13 (Trixie), armv7l |
| Waveshare 1.44" LCD HAT | ST7735S, 128×128, SPI. Includes 5-position joystick and 3 push buttons |
| Geekworm X306 V1.5 UPS | Single-cell 18650 UPS for the Pi Zero 2W. Battery level is indicated by 4 blue LEDs on the board only — it cannot be read via software |

The X306 connects to the Pi via pogo pins, and the LCD HAT stacks on top via the standard 40-pin GPIO header.

---

## Repository Layout

```
pipboy_mini.py          Main application
pipboy_mini_setup.sh    One-shot install and service setup script
VaultBoy.png            Vault Boy sprite (STAT screen)
inv.txt                 Inventory text (INV screen)
music/                  Drop .mp3 / .ogg / .wav files here (RADIO screen)
fonts/                  (Optional) custom .ttf fonts; see Fonts below
README.md               This file
```

---

## Setup

Copy all files to the Pi, then run the setup script once as root:

```bash
sudo bash pipboy_mini_setup.sh
```

The script does the following:

1. Creates the install directory (`~/pipboy_mini/`) and copies all project files into it.
2. Installs system packages: `python3-pil`, `python3-numpy`, `lgpio`, `alsa-utils`.
3. Installs Python packages via pip: `spidev`, `pygame`.
4. Enables SPI and adds the GPIO pull-up line to `/boot/config.txt` (required for the HAT's buttons to register correctly on Trixie).
5. Creates and enables a systemd service (`pipboy-mini`) so the application starts automatically on boot.

A reboot is required after the first run for the `config.txt` changes to take effect.

### Running Manually

Useful during development or if you want to see stdout/stderr directly:

```bash
cd ~/pipboy_mini
sudo python3 pipboy_mini.py
```

Press `Ctrl+C` to exit cleanly.

---

## Screens

Navigation between screens is handled by the joystick left and right directions. The screen indicator in the top-right corner of the header shows your current position.

### STAT

The welcome screen. Displays the Vault Boy sprite and a short message. No interactive controls — just joystick left/right to move on.

### INV

A scrollable text viewer for `inv.txt`. The file is plain text, one line per row on screen. Lines longer than roughly 20 characters will be clipped to fit the display width.

| Control | Action |
|---|---|
| Joystick Up / Down | Scroll through the file |
| Joystick Press (Select) | Reload `inv.txt` from disk |

The reload-on-select behaviour means you can edit `inv.txt` over SSH while the Pi is running and just press the joystick centre button to pick up the changes without restarting anything.

### DATA

A system information dashboard. Updates live on every frame.

| Field | Source |
|---|---|
| CPU | Usage percentage, sampled between frames via `/proc/stat` |
| RAM | Used / total in MB, from `/proc/meminfo` |
| DISK | Used / total in MB for the root partition |
| IP | First address returned by `hostname -I` |
| UP | System uptime from `/proc/uptime` |
| TEMP | CPU temperature from the thermal zone sysfs interface |

### RADIO

An MP3 player for audio files in the `music/` directory. Supported formats: `.mp3`, `.ogg`, `.wav`. Tracks are listed alphabetically. The currently playing track is highlighted in cyan with a `>` prefix; the cursor position is marked with `*`.

| Control | Action |
|---|---|
| Joystick Up / Down | Move the cursor through the track list |
| Joystick Press (Select) | Play the track under the cursor |
| KEY 1 | Play / Pause |
| KEY 2 | Next track |
| KEY 3 | Stop |

Tracks auto-advance when they finish. If no audio device is available (the Pi Zero 2W has no built-in audio output), the screen still fully functions — the track list, cursor, and controls all work, but no sound is produced. Attaching a USB audio adapter or pairing Bluetooth audio before starting the application will enable playback.

---

## Shutdown

There is no physical power button on the Pi Zero 2W / X306 stack, so pulling the plug without a clean shutdown risks SD card corruption. PipBoy Mini lets you power off safely from any screen.

Hold **KEY 1 and KEY 2 simultaneously**. A confirmation screen appears with a 3-second countdown and a draining progress bar. If the countdown completes, the application cleans up (stops audio, blanks the display, releases GPIO) and issues `sudo systemctl poweroff`.

Press any single button during the countdown to cancel and return to wherever you were.

---

## Controls Reference

All controls map to the physical joystick and three buttons on the Waveshare LCD HAT.

| Input | GPIO | Global Action | Screen-Specific Action |
|---|---|---|---|
| Joystick Up | 6 | — | INV: scroll up. RADIO: cursor up |
| Joystick Down | 19 | — | INV: scroll down. RADIO: cursor down |
| Joystick Left | 5 | Previous screen | — |
| Joystick Right | 26 | Next screen | — |
| Joystick Press | 13 | — | INV: reload file. RADIO: play selected track |
| KEY 1 | 21 | — | RADIO: play / pause |
| KEY 2 | 20 | — | RADIO: next track |
| KEY 3 | 16 | — | RADIO: stop |
| KEY 1 + KEY 2 (held) | 21 + 20 | Enter shutdown countdown (any screen) | — |

---

## Fonts

The application looks for TrueType fonts in this order:

1. The `fonts/` directory in the project folder.
2. System fonts: DejaVu Sans Mono → Liberation Mono → FreeMono.
3. PIL's built-in bitmap font as a last resort.

To use a custom font, drop a `.ttf` file into `fonts/` and update the `_load_font()` calls in `pipboy_mini.py` to reference it by filename.

---

## Battery

The Geekworm X306 V1.5 does not expose battery level via any GPIO pin or software interface. The four blue LEDs on the X306 board are the only indicator — 25%, 50%, 75%, 100%.
