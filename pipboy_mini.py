#!/usr/bin/env python3
"""
=============================================================================
  PIPBOY MINI - A Fallout-style Pip-Boy interface
  for Waveshare 1.44" LCD HAT + Raspberry Pi Zero 2W + Geekworm X306 UPS
=============================================================================

  SCREENS:
    STAT  - System info (CPU, RAM, Disk, IP, Uptime, Battery status note)
    INV   - Inventory loaded from ./inv.txt
    RADIO - MP3 player for files in ./music/

  CONTROLS (Waveshare 1.44" LCD HAT GPIO mapping):
    Joystick Up    -> GPIO 6   : Navigate up / scroll up
    Joystick Down  -> GPIO 19  : Navigate down / scroll down
    Joystick Left  -> GPIO 5   : Previous screen
    Joystick Right -> GPIO 26  : Next screen
    Joystick Press -> GPIO 13  : Select / confirm action
    KEY 1          -> GPIO 21  : Context action (Play/Pause on RADIO)
    KEY 2          -> GPIO 20  : Context action (Next track on RADIO)
    KEY 3          -> GPIO 16  : Context action (Stop on RADIO)

  DEPENDENCIES:
    sudo apt-get install python3-pil python3-numpy pygame
    sudo pip3 install spidev --break-system-packages
    (lgpio or RPi.GPIO — lgpio preferred on Trixie)

  DIRECTORY LAYOUT:
    pipboy_mini.py
    inv.txt            <- your inventory text
    music/             <- folder containing .mp3 files
    fonts/             <- (optional) .ttf fonts; falls back to PIL defaults

  NOTE ON BATTERY:
    The Geekworm X306 V1.5 does NOT expose battery level via software or GPIO.
    The STAT screen shows a visual indicator based on the 4 blue LEDs on the
    X306 board itself — you must read those physically. The on-screen battery
    icon is a reminder / placeholder that displays "CHECK LEDS" prompting you
    to glance at the hardware indicator.
=============================================================================
"""

import sys
import os
import time
import threading
import subprocess
import shutil

# ---------------------------------------------------------------------------
# GPIO backend selection — tries lgpio first (standard on Debian 13 Trixie),
# falls back to RPi.GPIO
# ---------------------------------------------------------------------------
try:
    import lgpio
    # lgpio renamed these constants between 0.1.6.0 and 0.2.0.0.
    # Apply the same compatibility shim that gpiozero/rpi-lgpio use.
    try:
        lgpio.SET_PULL_UP
    except AttributeError:
        lgpio.SET_PULL_NONE = lgpio.SET_BIAS_DISABLE
        lgpio.SET_PULL_UP   = lgpio.SET_BIAS_PULL_UP
        lgpio.SET_PULL_DOWN = lgpio.SET_BIAS_PULL_DOWN
    GPIO_BACKEND = "lgpio"
except ImportError:
    try:
        import RPi.GPIO as GPIO
        GPIO_BACKEND = "rpigpio"
    except ImportError:
        print("ERROR: No GPIO library found. Install lgpio or RPi.GPIO.")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Display driver — uses the Waveshare ST7735S via SPI.  This is a slimmed
# down version of their demo driver; the full version ships in the 7z archive.
# ---------------------------------------------------------------------------
import spidev
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# ---------------------------------------------------------------------------
# Audio — pygame.mixer for MP3 playback.  Install with:
#   sudo apt-get install python3-pygame
# ---------------------------------------------------------------------------
try:
    import pygame
    # On a headless Pi with no ALSA output, mixer.init() will throw.
    # Try real audio first; fall back to the dummy driver so the mixer
    # object exists and we can attempt playback later (e.g. after a USB
    # audio device is plugged in, or via Bluetooth).
    os.environ.setdefault("SDL_AUDIODRIVER", "alsa")
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    try:
        pygame.mixer.init()
    except pygame.error:
        # Real driver failed — fall back to dummy so mixer exists
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.init()
        print("WARNING: No audio device found. RADIO playback will not produce sound.")
    AUDIO_AVAILABLE = True
except Exception as e:
    AUDIO_AVAILABLE = False
    print(f"WARNING: pygame audio not available ({e}). RADIO screen will be limited.")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Display
DISP_WIDTH  = 128
DISP_HEIGHT = 128
DISP_ROTATE = 0   # 0, 90, 180, 270 — adjust if your physical orientation differs

# SPI pins (fixed by Waveshare HAT hardware wiring)
PIN_RST = 27
PIN_DC  = 25
# PIN_CS (GPIO 8) is owned by the kernel SPI subsystem via spidev.open(0,0).
# Do NOT claim or toggle it manually — lgpio/RPi.GPIO will raise "GPIO busy".
PIN_BL  = 24  # backlight (active LOW on some boards, active HIGH on others)

# Joystick & button GPIO pins (from Waveshare key_demo.py / config.txt overlay)
PIN_JOY_UP    = 6
PIN_JOY_DOWN  = 19
PIN_JOY_LEFT  = 5
PIN_JOY_RIGHT = 26
PIN_JOY_PRESS = 13
PIN_KEY1      = 21
PIN_KEY2      = 20
PIN_KEY3      = 16

ALL_INPUT_PINS = [
    PIN_JOY_UP, PIN_JOY_DOWN, PIN_JOY_LEFT, PIN_JOY_RIGHT, PIN_JOY_PRESS,
    PIN_KEY1, PIN_KEY2, PIN_KEY3
]

# File paths (relative to script location)
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
INV_FILE    = os.path.join(SCRIPT_DIR, "inv.txt")
MUSIC_DIR   = os.path.join(SCRIPT_DIR, "music")
FONT_DIR    = os.path.join(SCRIPT_DIR, "fonts")

# Colour palette — classic Pip-Boy green-on-black with accent variations
CLR_BG       = (0,   0,   0)    # black background
CLR_GREEN    = (0,   255, 0)    # primary Pip-Boy green
CLR_GREEN_DIM = (0,  140, 0)    # dimmed green for inactive / secondary text
CLR_GREEN_MID = (0,  200, 0)    # mid-brightness green
CLR_AMBER    = (255, 191, 0)    # amber accent for warnings / highlights
CLR_WHITE    = (255, 255, 255)
CLR_GREY     = (100, 100, 100)
CLR_CYAN     = (0,   200, 200)  # subtle accent for selected items

# Timing
INPUT_DEBOUNCE_MS = 150   # minimum ms between repeated key events
REFRESH_RATE_HZ   = 10    # screen redraws per second


# =============================================================================
# ST7735S DISPLAY DRIVER (minimal — SPI only)
# =============================================================================

class ST7735Display:
    """Bare-bones driver for the ST7735S 128x128 LCD via 4-wire SPI."""

    # ST7735 command bytes
    _SWRESET = 0x01
    _SLPOUT  = 0x11
    _COLMOD  = 0x3A
    _MADCTL  = 0x36
    _CASET   = 0x2A
    _RASET   = 0x2B
    _RAMWR   = 0x2C
    _DISPON  = 0x29
    _INVON   = 0x21

    # MADCTL bits
    _MADCTL_MY  = 0x80
    _MADCTL_MX  = 0x40
    _MADCTL_MV  = 0x20
    _MADCTL_ML  = 0x10
    _MADCTL_RGB = 0x00
    _MADCTL_BGR = 0x08

    def __init__(self):
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 40_000_000
        self.spi.mode = 0

        self._pin_setup()
        self._init_display()

    # --- GPIO helpers (backend-agnostic) -----------------------------------
    def _pin_setup(self):
        if GPIO_BACKEND == "lgpio":
            self._chip = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._chip, PIN_RST)
            lgpio.gpio_claim_output(self._chip, PIN_DC)
            lgpio.gpio_claim_output(self._chip, PIN_BL)
        else:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(PIN_RST, GPIO.OUT)
            GPIO.setup(PIN_DC,  GPIO.OUT)
            GPIO.setup(PIN_BL,  GPIO.OUT)

    def _pin_high(self, pin):
        if GPIO_BACKEND == "lgpio":
            lgpio.gpio_write(self._chip, pin, 1)
        else:
            GPIO.output(pin, GPIO.HIGH)

    def _pin_low(self, pin):
        if GPIO_BACKEND == "lgpio":
            lgpio.gpio_write(self._chip, pin, 0)
        else:
            GPIO.output(pin, GPIO.LOW)

    # --- Init sequence -----------------------------------------------------
    def _init_display(self):
        self._pin_low(PIN_RST)
        time.sleep(0.1)
        self._pin_high(PIN_RST)
        time.sleep(0.1)

        self._send_command(self._SWRESET)
        time.sleep(0.15)
        self._send_command(self._SLPOUT)
        time.sleep(0.15)
        self._send_command(self._COLMOD, [0x55])   # 16-bit RGB565
        self._send_command(self._MADCTL, [self._MADCTL_MX | self._MADCTL_MV | self._MADCTL_RGB])
        self._send_command(self._INVON)
        self._send_command(self._DISPON)

        # Backlight on
        self._pin_high(PIN_BL)

    # --- Low-level SPI send ------------------------------------------------
    def _send_command(self, cmd, data=None):
        self._pin_low(PIN_DC)          # command mode
        self.spi.xfer2([cmd])
        if data:
            self._pin_high(PIN_DC)     # data mode
            self.spi.xfer2(data)

    # --- Public: blit a PIL Image to the display ---------------------------
    def show_image(self, img: Image.Image):
        """Send a 128x128 RGB PIL image to the display."""
        if img.size != (DISP_WIDTH, DISP_HEIGHT):
            img = img.resize((DISP_WIDTH, DISP_HEIGHT))

        # Convert to RGB565 byte array
        rgb = np.array(img.convert("RGB"), dtype=np.uint16)
        r = (rgb[:, :, 0] >> 3).astype(np.uint16)
        g = (rgb[:, :, 1] >> 2).astype(np.uint16)
        b = (rgb[:, :, 2] >> 3).astype(np.uint16)
        pixel16 = (r << 11) | (g << 5) | b
        buf = pixel16.astype(">u2").tobytes()   # big-endian 16-bit

        # Set full-screen write window
        self._send_command(self._CASET, [0x00, 0x01, 0x00, DISP_WIDTH])  # col 1..128
        self._send_command(self._RASET, [0x00, 0x00, 0x00, DISP_HEIGHT - 1])

        # Blast pixel data
        self._pin_low(PIN_DC)
        self.spi.xfer2([self._RAMWR])
        self._pin_high(PIN_DC)
        # SPI xfer2 max buffer is typically 4096 bytes on Linux; chunk it
        chunk = 4096
        for i in range(0, len(buf), chunk):
            self.spi.xfer2(list(buf[i:i+chunk]))

    def cleanup(self):
        self._pin_low(PIN_BL)
        self.spi.close()
        if GPIO_BACKEND == "lgpio":
            lgpio.gpiochip_close(self._chip)
        else:
            GPIO.cleanup([PIN_RST, PIN_DC, PIN_BL])


# =============================================================================
# INPUT MANAGER  — edge-triggered, debounced button reader
# =============================================================================

# Named events (kept as simple strings for readability)
EVT_UP    = "UP"
EVT_DOWN  = "DOWN"
EVT_LEFT  = "LEFT"
EVT_RIGHT = "RIGHT"
EVT_SEL   = "SELECT"
EVT_KEY1  = "KEY1"
EVT_KEY2  = "KEY2"
EVT_KEY3  = "KEY3"

PIN_TO_EVT = {
    PIN_JOY_UP:    EVT_UP,
    PIN_JOY_DOWN:  EVT_DOWN,
    PIN_JOY_LEFT:  EVT_LEFT,
    PIN_JOY_RIGHT: EVT_RIGHT,
    PIN_JOY_PRESS: EVT_SEL,
    PIN_KEY1:      EVT_KEY1,
    PIN_KEY2:      EVT_KEY2,
    PIN_KEY3:      EVT_KEY3,
}


class InputManager:
    """
    Polls all input pins on every tick.  Generates an event string on the
    falling edge (button pressed) with software debounce.  Thread-safe —
    the main loop can call get_event() each frame.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._event_queue = []
        self._last_state = {}      # pin -> bool (True = pressed)
        self._last_time  = {}      # pin -> timestamp of last accepted event
        self._chip = None

        if GPIO_BACKEND == "lgpio":
            self._chip = lgpio.gpiochip_open(0)
            for pin in ALL_INPUT_PINS:
                lgpio.gpio_claim_input(self._chip, pin, lgpio.SET_PULL_UP)
        else:
            GPIO.setmode(GPIO.BCM)
            for pin in ALL_INPUT_PINS:
                GPIO.setup(pin, GPIO.IN, pull_up_or_down=GPIO.PUD_UP)

        for pin in ALL_INPUT_PINS:
            self._last_state[pin] = False
            self._last_time[pin]  = 0

    def _read_pin(self, pin) -> bool:
        """Return True if the pin is currently pressed (active-low)."""
        if GPIO_BACKEND == "lgpio":
            return lgpio.gpio_read(self._chip, pin) == 0
        else:
            return GPIO.input(pin) == GPIO.LOW

    def poll(self):
        """Call once per frame.  Detects new presses and queues events."""
        now = time.time() * 1000  # ms
        for pin in ALL_INPUT_PINS:
            pressed = self._read_pin(pin)
            was_pressed = self._last_state[pin]
            if pressed and not was_pressed:
                # Rising edge (active-low → press detected)
                if (now - self._last_time[pin]) >= INPUT_DEBOUNCE_MS:
                    with self._lock:
                        self._event_queue.append(PIN_TO_EVT[pin])
                    self._last_time[pin] = now
            self._last_state[pin] = pressed

    def get_event(self):
        """Return the next pending event string, or None."""
        with self._lock:
            if self._event_queue:
                return self._event_queue.pop(0)
        return None

    def cleanup(self):
        if GPIO_BACKEND == "lgpio" and self._chip is not None:
            lgpio.gpiochip_close(self._chip)
        else:
            GPIO.cleanup(ALL_INPUT_PINS)


# =============================================================================
# FONT HELPERS
# =============================================================================

def _load_font(name_or_path, size):
    """Try to load a TTF font; fall back to PIL default bitmap font."""
    # Try the fonts/ directory first
    candidate = os.path.join(FONT_DIR, name_or_path)
    if os.path.isfile(candidate):
        return ImageFont.truetype(candidate, size)
    # Try as an absolute path
    if os.path.isfile(name_or_path):
        return ImageFont.truetype(name_or_path, size)
    # Common system monospace fallbacks
    for system_font in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]:
        if os.path.isfile(system_font):
            return ImageFont.truetype(system_font, size)
    # Ultimate fallback — PIL built-in bitmap
    return ImageFont.load_default()


# Pre-load fonts at module level (sized for 128x128 pixel screen)
FONT_TITLE  = _load_font("DejaVuSansMono.ttf", 11)   # screen titles
FONT_BODY   = _load_font("DejaVuSansMono.ttf", 9)    # body / data text
FONT_SMALL  = _load_font("DejaVuSansMono.ttf", 8)    # fine detail text
FONT_BIG    = _load_font("DejaVuSansMono.ttf", 13)   # large labels


# =============================================================================
# SHARED DRAWING UTILITIES
# =============================================================================

def draw_header(draw: ImageDraw.ImageDraw, title: str, screen_index: int, screen_count: int):
    """Draw the top header bar: left-aligned title + right-aligned screen nav."""
    # Background bar
    draw.rectangle([(0, 0), (DISP_WIDTH - 1, 14)], fill=CLR_GREEN_DIM)
    # Title
    draw.text((3, 1), title, fill=CLR_GREEN, font=FONT_TITLE)
    # Screen indicator (e.g. "2/3")
    nav_text = f"{screen_index+1}/{screen_count}"
    bbox = draw.textbbox((0, 0), nav_text, font=FONT_SMALL)
    nav_w = bbox[2] - bbox[0]
    draw.text((DISP_WIDTH - nav_w - 3, 2), nav_text, fill=CLR_GREEN_MID, font=FONT_SMALL)


def draw_footer(draw: ImageDraw.ImageDraw, hints: str):
    """Draw a small footer bar with contextual button hints."""
    draw.rectangle([(0, DISP_HEIGHT - 13), (DISP_WIDTH - 1, DISP_HEIGHT - 1)], fill=CLR_GREEN_DIM)
    draw.text((2, DISP_HEIGHT - 12), hints, fill=CLR_GREEN_MID, font=FONT_SMALL)


def draw_divider(draw: ImageDraw.ImageDraw, y: int):
    """Horizontal green divider line."""
    draw.line([(0, y), (DISP_WIDTH - 1, y)], fill=CLR_GREEN_DIM, width=1)


def new_frame() -> (Image.Image, ImageDraw.ImageDraw):
    """Create a fresh black frame buffer and its drawing context."""
    img = Image.new("RGB", (DISP_WIDTH, DISP_HEIGHT), CLR_BG)
    return img, ImageDraw.Draw(img)


# =============================================================================
# SCREEN: STAT
# =============================================================================

def _get_cpu_percent() -> str:
    """Read CPU usage from /proc/stat (single-shot, non-blocking)."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        # idle is field index 4
        idle = int(parts[4])
        total = sum(int(x) for x in parts[1:])
        # We only have an instant snapshot; store for next call
        if not hasattr(_get_cpu_percent, '_prev'):
            _get_cpu_percent._prev = (idle, total)
            return "N/A"
        prev_idle, prev_total = _get_cpu_percent._prev
        _get_cpu_percent._prev = (idle, total)
        d_idle  = idle - prev_idle
        d_total = total - prev_total
        if d_total == 0:
            return "0%"
        return f"{int((1.0 - d_idle / d_total) * 100)}%"
    except Exception:
        return "ERR"


def _get_ram_info() -> (str, str):
    """Return (used_str, total_str) from /proc/meminfo in MB."""
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                mem[parts[0].rstrip(":")] = int(parts[1])  # kB
        total_mb = mem["MemTotal"] // 1024
        avail_mb = mem["MemAvailable"] // 1024
        used_mb  = total_mb - avail_mb
        return f"{used_mb}MB", f"{total_mb}MB"
    except Exception:
        return "ERR", "ERR"


def _get_disk_info() -> (str, str):
    """Return (used_str, total_str) for the root partition in MB."""
    try:
        st = os.statvfs("/")
        total_mb = (st.f_blocks * st.f_frsize) // (1024 * 1024)
        free_mb  = (st.f_bavail * st.f_frsize) // (1024 * 1024)
        used_mb  = total_mb - free_mb
        return f"{used_mb}MB", f"{total_mb}MB"
    except Exception:
        return "ERR", "ERR"


def _get_ip_address() -> str:
    """Best-effort local IP via hostname -I."""
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2
        )
        addrs = result.stdout.strip().split()
        return addrs[0] if addrs else "No IP"
    except Exception:
        return "No IP"


def _get_uptime() -> str:
    """Human-readable uptime string."""
    try:
        with open("/proc/uptime") as f:
            secs = float(f.readline().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        else:
            return f"{s}s"
    except Exception:
        return "ERR"


def _get_cpu_temp() -> str:
    """Read CPU temperature (Raspbian thermal zone)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            millideg = int(f.read().strip())
        return f"{millideg // 1000}C"
    except Exception:
        return "N/A"


class StatScreen:
    """STAT screen — system information dashboard."""

    def __init__(self):
        # Kick off the first CPU read so we have a baseline on the next frame
        _get_cpu_percent()

    def handle_event(self, evt):
        # STAT screen has no interactive elements; all nav is handled by main loop
        pass

    def draw(self) -> Image.Image:
        img, draw = new_frame()

        # --- Header ---
        draw_header(draw, "STAT", 0, 3)

        # --- Body content ---
        y = 19  # start below header
        line_h = 12

        cpu   = _get_cpu_percent()
        ram_used, ram_total = _get_ram_info()
        disk_used, disk_total = _get_disk_info()
        ip    = _get_ip_address()
        up    = _get_uptime()
        temp  = _get_cpu_temp()

        lines = [
            ("CPU",   cpu),
            ("RAM",   f"{ram_used}/{ram_total}"),
            ("DISK",  f"{disk_used}/{disk_total}"),
            ("IP",    ip),
            ("UP",    up),
            ("TEMP",  temp),
            ("BATT",  "SEE X306 LEDS"),
        ]

        for label, value in lines:
            # Label (dim green, left-aligned)
            draw.text((4, y), f"{label}:", fill=CLR_GREEN_DIM, font=FONT_BODY)
            # Value (bright green, indented)
            label_w = draw.textbbox((0, 0), f"{label}:", font=FONT_BODY)[2]
            draw.text((6 + label_w, y), value, fill=CLR_GREEN, font=FONT_BODY)
            y += line_h

        # Decorative divider above battery note
        draw_divider(draw, y - 2)
        y += 2

        # Battery note box
        draw.rectangle([(2, y), (DISP_WIDTH - 3, y + 16)], outline=CLR_AMBER, fill=(20, 10, 0))
        draw.text((5, y + 2), "BATT: Read X306", fill=CLR_AMBER, font=FONT_SMALL)
        draw.text((5, y + 9), "4 blue LEDs on board", fill=CLR_AMBER, font=FONT_SMALL)

        # --- Footer ---
        draw_footer(draw, "<> switch screen")

        return img


# =============================================================================
# SCREEN: INV (Inventory)
# =============================================================================

class InvScreen:
    """INV screen — scrollable text viewer for inv.txt."""

    def __init__(self):
        self._lines = []
        self._scroll_offset = 0
        self._load_file()

    def _load_file(self):
        """(Re)load inv.txt into memory."""
        try:
            with open(INV_FILE, "r") as f:
                self._lines = f.read().splitlines()
        except FileNotFoundError:
            self._lines = [
                "[ inv.txt not found ]",
                "",
                "Create inv.txt in the",
                "same directory as",
                "pipboy_mini.py to populate",
                "your inventory.",
            ]
        except Exception as e:
            self._lines = [f"ERROR: {e}"]

    def handle_event(self, evt):
        max_scroll = max(0, len(self._lines) - self._visible_lines())
        if evt == EVT_UP:
            self._scroll_offset = max(0, self._scroll_offset - 1)
        elif evt == EVT_DOWN:
            self._scroll_offset = min(max_scroll, self._scroll_offset + 1)
        elif evt == EVT_SEL:
            # Re-read the file on SELECT (handy for hot-editing)
            self._load_file()
            self._scroll_offset = 0

    def _visible_lines(self) -> int:
        """How many text lines fit in the body area."""
        body_top    = 17
        body_bottom = DISP_HEIGHT - 15
        return (body_bottom - body_top) // 10  # ~10 px per line

    def draw(self) -> Image.Image:
        img, draw = new_frame()

        draw_header(draw, "INV", 1, 3)

        y = 18
        line_h = 10
        visible = self._visible_lines()

        for i in range(visible):
            idx = self._scroll_offset + i
            if idx >= len(self._lines):
                break
            line = self._lines[idx]
            # Highlight alternating rows subtly
            if i % 2 == 0:
                draw.rectangle([(1, y - 1), (DISP_WIDTH - 2, y + line_h - 2)],
                               fill=(0, 12, 0))
            # Clip long lines to screen width
            draw.text((3, y), line[:20], fill=CLR_GREEN, font=FONT_BODY)
            y += line_h

        # Scroll indicator on right edge
        if len(self._lines) > visible:
            track_top    = 18
            track_bottom = DISP_HEIGHT - 15
            track_h      = track_bottom - track_top
            thumb_h      = max(8, int(track_h * visible / len(self._lines)))
            thumb_pos    = track_top + int(
                (track_h - thumb_h) * self._scroll_offset /
                max(1, len(self._lines) - visible)
            )
            draw.rectangle([(DISP_WIDTH - 4, track_top),
                            (DISP_WIDTH - 2, track_bottom)], fill=CLR_GREEN_DIM)
            draw.rectangle([(DISP_WIDTH - 4, thumb_pos),
                            (DISP_WIDTH - 2, thumb_pos + thumb_h)], fill=CLR_GREEN)

        draw_footer(draw, "^v scroll  SEL reload")

        return img


# =============================================================================
# SCREEN: RADIO (MP3 Player)
# =============================================================================

class RadioScreen:
    """RADIO screen — simple MP3 player for files in ./music/."""

    def __init__(self):
        self._tracks = []
        self._current = 0       # index into _tracks
        self._playing = False
        self._selected = 0      # cursor position in the track list
        self._load_tracks()

    # --- Track discovery ---------------------------------------------------
    def _load_tracks(self):
        self._tracks = []
        if not os.path.isdir(MUSIC_DIR):
            os.makedirs(MUSIC_DIR, exist_ok=True)
        for fname in sorted(os.listdir(MUSIC_DIR)):
            if fname.lower().endswith((".mp3", ".ogg", ".wav")):
                self._tracks.append(fname)

    # --- Playback control --------------------------------------------------
    def _play_track(self, index: int):
        """Start (or restart) playback of track at index."""
        if not AUDIO_AVAILABLE or not self._tracks:
            return
        self._stop()
        self._current = index % len(self._tracks) if self._tracks else 0
        path = os.path.join(MUSIC_DIR, self._tracks[self._current])
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self._playing = True
        except Exception:
            self._playing = False

    def _stop(self):
        if AUDIO_AVAILABLE:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self._playing = False

    def _toggle_pause(self):
        if not AUDIO_AVAILABLE or not self._tracks:
            return
        if not self._playing:
            # If nothing is playing, start current track
            self._play_track(self._current)
            return
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self._playing = False
        else:
            pygame.mixer.music.unpause()
            self._playing = True

    def _next_track(self):
        if not self._tracks:
            return
        self._play_track((self._current + 1) % len(self._tracks))
        self._selected = self._current

    # --- Check if track ended spontaneously --------------------------------
    def _check_ended(self):
        if self._playing and AUDIO_AVAILABLE:
            if not pygame.mixer.music.get_busy():
                # Track finished naturally — move to next
                self._current = (self._current + 1) % len(self._tracks) if self._tracks else 0
                self._play_track(self._current)
                self._selected = self._current

    # --- Event handling ----------------------------------------------------
    def handle_event(self, evt):
        if not self._tracks:
            return  # no tracks; nothing to do

        if evt == EVT_UP:
            self._selected = (self._selected - 1) % len(self._tracks)
        elif evt == EVT_DOWN:
            self._selected = (self._selected + 1) % len(self._tracks)
        elif evt == EVT_SEL:
            # Play the selected track
            self._play_track(self._selected)
        elif evt == EVT_KEY1:
            # Play / Pause
            self._toggle_pause()
        elif evt == EVT_KEY2:
            # Next track
            self._next_track()
        elif evt == EVT_KEY3:
            # Stop
            self._stop()

    # --- Rendering ---------------------------------------------------------
    def draw(self) -> Image.Image:
        self._check_ended()

        img, draw = new_frame()
        draw_header(draw, "RADIO", 2, 3)

        if not self._tracks:
            # Empty state
            draw.text((8, 40), "No audio files found", fill=CLR_GREEN_DIM, font=FONT_BODY)
            draw.text((8, 52), "Put .mp3/.ogg/.wav", fill=CLR_GREEN_DIM, font=FONT_BODY)
            draw.text((8, 64), "into ./music/", fill=CLR_GREEN_DIM, font=FONT_BODY)
            draw_footer(draw, "")
            return img

        # --- Now-playing indicator ---
        y = 18
        status_str = "PLAYING" if self._playing else "STOPPED"
        status_col = CLR_GREEN if self._playing else CLR_GREEN_DIM
        draw.text((4, y), f"[{status_str}]", fill=status_col, font=FONT_BODY)

        if self._tracks:
            # Truncate current track name
            cur_name = self._tracks[self._current]
            if len(cur_name) > 18:
                cur_name = cur_name[:15] + "..."
            draw.text((4, y + 10), cur_name, fill=CLR_CYAN, font=FONT_BODY)

        draw_divider(draw, y + 22)

        # --- Track list ---
        list_top    = y + 25
        line_h      = 10
        visible     = max(1, (DISP_HEIGHT - 15 - list_top) // line_h)
        # Ensure selected track is visible (auto-scroll)
        scroll = 0
        if self._selected >= visible:
            scroll = self._selected - visible + 1

        for i in range(visible):
            idx = scroll + i
            if idx >= len(self._tracks):
                break
            track_y = list_top + i * line_h
            name = self._tracks[idx]
            if len(name) > 18:
                name = name[:15] + "..."

            is_selected = (idx == self._selected)
            is_playing  = (idx == self._current and self._playing)

            # Selection highlight
            if is_selected:
                draw.rectangle([(1, track_y - 1), (DISP_WIDTH - 2, track_y + line_h - 2)],
                               fill=(0, 30, 10))

            # Prefix markers
            prefix = "  "
            if is_playing:
                prefix = "> "   # playing indicator
            elif is_selected:
                prefix = "* "   # cursor

            col = CLR_GREEN if is_selected else CLR_GREEN_DIM
            if is_playing:
                col = CLR_CYAN
            draw.text((3, track_y), prefix + name, fill=col, font=FONT_SMALL)

        # Scroll indicator
        if len(self._tracks) > visible:
            track_top_px    = list_top
            track_bottom_px = DISP_HEIGHT - 15
            track_h         = track_bottom_px - track_top_px
            thumb_h         = max(6, int(track_h * visible / len(self._tracks)))
            thumb_pos       = track_top_px + int(
                (track_h - thumb_h) * scroll / max(1, len(self._tracks) - visible)
            )
            draw.rectangle([(DISP_WIDTH - 4, track_top_px),
                            (DISP_WIDTH - 2, track_bottom_px)], fill=CLR_GREEN_DIM)
            draw.rectangle([(DISP_WIDTH - 4, thumb_pos),
                            (DISP_WIDTH - 2, thumb_pos + thumb_h)], fill=CLR_GREEN)

        draw_footer(draw, "K1:play K2:next K3:stop")

        return img

    def cleanup(self):
        self._stop()


# =============================================================================
# MAIN APPLICATION LOOP
# =============================================================================

class PipBoyMini:
    """Top-level application: owns display, input, and screens."""

    SCREENS = ["STAT", "INV", "RADIO"]

    def __init__(self):
        print("[PipBoy Mini] Initialising display...")
        self.display = ST7735Display()

        print("[PipBoy Mini] Initialising input...")
        self.input = InputManager()

        print("[PipBoy Mini] Loading screens...")
        self.screens = [
            StatScreen(),
            InvScreen(),
            RadioScreen(),
        ]
        self.current_screen = 0   # start on STAT

        self._running = True

    # --- Main loop ---------------------------------------------------------
    def run(self):
        print("[PipBoy Mini] Running.  Press Ctrl+C to exit.")
        interval = 1.0 / REFRESH_RATE_HZ

        while self._running:
            t0 = time.time()

            # 1. Poll input
            self.input.poll()
            evt = self.input.get_event()

            # 2. Process event
            if evt:
                if evt == EVT_LEFT:
                    self.current_screen = (self.current_screen - 1) % len(self.screens)
                elif evt == EVT_RIGHT:
                    self.current_screen = (self.current_screen + 1) % len(self.screens)
                else:
                    # Pass event down to current screen
                    self.screens[self.current_screen].handle_event(evt)

            # 3. Render current screen
            frame = self.screens[self.current_screen].draw()

            # 4. Push frame to display
            self.display.show_image(frame)

            # 5. Sleep remainder of frame budget
            elapsed = time.time() - t0
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # --- Graceful shutdown -------------------------------------------------
    def cleanup(self):
        print("[PipBoy Mini] Shutting down...")
        self._running = False
        # Stop audio
        if hasattr(self.screens[2], 'cleanup'):
            self.screens[2].cleanup()
        # Blank display and release GPIO
        try:
            blank = Image.new("RGB", (DISP_WIDTH, DISP_HEIGHT), CLR_BG)
            self.display.show_image(blank)
            self.display.cleanup()
        except Exception:
            pass
        self.input.cleanup()
        if GPIO_BACKEND == "rpigpio":
            GPIO.cleanup()
        print("[PipBoy Mini] Goodbye, Vault Dweller.")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    app = PipBoyMini()
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
