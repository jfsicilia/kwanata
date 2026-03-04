#!/bin/bash

# --- Path Definitions (XDG Standards) ---
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/kwanata"
CONFIG_DIR="$HOME/.config/kwanata"
STATE_DIR="$HOME/.local/state/kwanata"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "🚀 Starting Kwanata installation..."

# 1. Create directory structure
mkdir -p "$BIN_DIR" "$LIB_DIR" "$CONFIG_DIR" "$STATE_DIR" "$SERVICE_DIR"

# 2. Deploy Python Daemon
if [ -f "focus_to_kanata.py" ]; then
    cp focus_to_kanata.py "$LIB_DIR/"
    chmod +x "$LIB_DIR/focus_to_kanata.py"
    # Create symlink for easy CLI access
    ln -sf "$LIB_DIR/focus_to_kanata.py" "$BIN_DIR/kwanata"
    echo "✅ Daemon installed to $LIB_DIR"
else
    echo "❌ Error: focus_to_kanata.py not found!"
    exit 1
fi

# 3. Deploy Configuration (Do not overwrite existing config)
if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    cp config.toml "$CONFIG_DIR/"
    echo "✅ Configuration created at $CONFIG_DIR"
else
    echo "⚠️ Existing config.toml detected, skipping copy to prevent overwriting settings."
fi

# 4. Deploy KWin Dynamic Script
cp kwin_script.js "$STATE_DIR/"
echo "✅ KWin script template placed in $STATE_DIR"

# 5. Install Systemd User Service
cp kwanata.service "$SERVICE_DIR/"

# 6. Reload Systemd daemon to recognize new service
systemctl --user daemon-reload

echo "--------------------------------------------------"
echo "🎉 Installation successful!"
echo "To enable and start kwanata: systemctl --user enable --now kwanata.service"
echo "To check status: systemctl --user status kwanata.service"
echo "To follow logs: journalctl --user -u kwanata.service -f"
echo "--------------------------------------------------"
