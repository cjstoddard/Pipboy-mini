# PipBoy Mini

A Fallout-style Pip-Boy interface for a Raspberry Pi Zero 2W, built around the Waveshare 1.44" LCD HAT. Four screens, joystick and button navigation, and an MP3 player — all on a 128×128 pixel display.

![Vault Boy](VaultBoy.png)

---

## Hardware

| Component | Notes | Link |
|---|---|---|
| Raspberry Pi Zero 2W | Runs Raspbian GNU/Linux 13 (Trixie), armv7l | [Raspberry Pi Zero 2WH](https://www.amazon.com/Raspberry-Pi-Zero-2-WH/dp/B0DB2JBD9C) |
| Waveshare 1.44" LCD HAT | ST7735S, 128×128, SPI. Includes 5-position joystick and 3 push buttons | [Waveshare 1.44inch LCD Display HAT](https://www.amazon.com/dp/B077YK8161?ref=ppx_yo2ov_dt_b_fed_asin_title&th=10 |
| Geekworm X306 V1.5 UPS | Single-cell 18650 UPS for the Pi Zero 2W. | [Geekworm X306 V1.5 UPS Expansion Board](https://www.amazon.com/dp/B0B74NT38D?ref=ppx_yo2ov_dt_b_fed_asin_title) |
| 18650 Battery | Single cell rechargable battery | [3.7 Volt Rechargeable Battery, 3000mAh Battery](https://www.amazon.com/dp/B0CRNSFQGX) |

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

---

## TODO

3D printed case and an armband of somekind

---

Copyrights and Trademarks: Both Fallout and Pipboy copyrights and trademarks belong to ZeniMax Media Inc and Bethesda Games. This project was developed for fun as part of a hobby, no infringment of any copyrights or trademarks is intended.

---

Disclaimer: This software is provided "AS IS", without warranty of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a paticular purpose and nonifringment. In no event shall the author or copyright holders be liable for any claim, damages or other liability, whether in an action of contract, tort or otherwise, arising from, out of or in connection with the software or the use or other dealings in the software.
