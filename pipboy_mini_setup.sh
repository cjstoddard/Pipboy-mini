#!/bin/bash
# =============================================================================
#  pipboy_mini_setup.sh
#  Run this ONCE on your Pi Zero 2W to install dependencies and configure
#  the PipBoy Mini to start automatically on boot.
#
#  Usage:  sudo bash pipboy_mini_setup.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
INSTALL_DIR="${USER_HOME}/pipboy_mini"

echo "=============================================="
echo "  PipBoy Mini — Setup Script"
echo "=============================================="

# --- 1. Create install directory and copy files ----------------------------
echo "[1/6] Setting up directories..."
mkdir -p "${INSTALL_DIR}/music"
mkdir -p "${INSTALL_DIR}/fonts"

# Copy main script and assets if they exist alongside this setup script
if [ -f "${SCRIPT_DIR}/pipboy_mini.py" ]; then
    cp "${SCRIPT_DIR}/pipboy_mini.py" "${INSTALL_DIR}/pipboy_mini.py"
fi
if [ -f "${SCRIPT_DIR}/inv.txt" ]; then
    cp "${SCRIPT_DIR}/inv.txt" "${INSTALL_DIR}/inv.txt"
fi
if [ -f "${SCRIPT_DIR}/VaultBoy.png" ]; then
    cp "${SCRIPT_DIR}/VaultBoy.png" "${INSTALL_DIR}/VaultBoy.png"
fi

chown -R "${SUDO_USER}:${SUDO_USER}" "${INSTALL_DIR}"
echo "    Install directory: ${INSTALL_DIR}"
echo "    Drop your .mp3 files into: ${INSTALL_DIR}/music/"

# --- 2. Install system packages --------------------------------------------
echo "[2/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3-pil \
    python3-numpy \
    lgpio \
    alsa-utils \
    sox \
    libsox-fmt-all 2>/dev/null || true

# --- 3. Install Python packages via pip ------------------------------------
echo "[3/6] Installing Python packages..."
pip3 install spidev pygame --break-system-packages 2>/dev/null || \
    sudo -u "$SUDO_USER" pip3 install spidev pygame --break-system-packages

# --- 4. Ensure SPI is enabled in config.txt --------------------------------
echo "[4/6] Checking SPI and GPIO pull-up configuration..."
CONFIG="/boot/config.txt"

# Enable SPI if not already
if ! grep -q "^dtparam=spi=on" "${CONFIG}"; then
    echo "dtparam=spi=on" >> "${CONFIG}"
    echo "    Added: dtparam=spi=on"
fi

# Add GPIO pull-ups for the Waveshare HAT buttons (required on Trixie)
# Only add if not already present
if ! grep -q "gpio=6,19,5,26,13,21,20,16=pu" "${CONFIG}"; then
    echo "gpio=6,19,5,26,13,21,20,16=pu" >> "${CONFIG}"
    echo "    Added: GPIO pull-up configuration for Waveshare HAT"
fi

# --- 5. Create systemd service file ----------------------------------------
echo "[5/6] Creating systemd service..."
SERVICE_FILE="/etc/systemd/system/pipboy-mini.service"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=PipBoy Mini — Fallout Pip-Boy interface
After=network.target sound.target
Wants=network.target

[Service]
Type=simple
User=${SUDO_USER}
Group=${SUDO_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/pipboy_mini.py
Restart=on-failure
RestartSec=5
# Give audio a moment to initialise
TimeoutStartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pipboy-mini.service
echo "    Service enabled: pipboy-mini"

# --- 6. Summary ------------------------------------------------------------
echo "[6/6] Done!"
echo ""
echo "=============================================="
echo "  Setup complete.  Summary:"
echo "=============================================="
echo ""
echo "  Install dir : ${INSTALL_DIR}"
echo "  Music dir   : ${INSTALL_DIR}/music/"
echo "  Inventory   : ${INSTALL_DIR}/inv.txt"
echo ""
echo "  The service will start automatically after"
echo "  reboot.  To start it now (before reboot):"
echo ""
echo "    sudo systemctl start pipboy-mini"
echo ""
echo "  To run manually (for testing / debugging):"
echo ""
echo "    cd ${INSTALL_DIR}"
echo "    sudo python3 pipboy_mini.py"
echo ""
echo "  NOTE: A reboot is required for the SPI and"
echo "  GPIO pull-up changes in config.txt to take"
echo "  effect."
echo "=============================================="
