#!/bin/bash

# --- Path Definitions ---
PROJECT_ROOT=$(pwd)
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/kwanata"
CONFIG_DIR="$HOME/.config/kwanata"
STATE_DIR="$HOME/.local/state/kwanata"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "🛠️  Setting up Kwanata in Development Mode (Symlinks)..."

# 1. Create necessary directory structure
mkdir -p "$BIN_DIR" "$LIB_DIR" "$CONFIG_DIR" "$STATE_DIR" "$SERVICE_DIR"

# 2. Link the Python Daemon
if [ -f "$PROJECT_ROOT/focus_to_kanata.py" ]; then
    # Link the source file to lib
    ln -sf "$PROJECT_ROOT/focus_to_kanata.py" "$LIB_DIR/focus_to_kanata.py"
    # Link to bin for global execution
    ln -sf "$LIB_DIR/focus_to_kanata.py" "$BIN_DIR/kwanata"
    chmod +x "$PROJECT_ROOT/focus_to_kanata.py"
    echo "✅ Symlink created: $BIN_DIR/kwanata -> $PROJECT_ROOT/focus_to_kanata.py"
else
    echo "❌ Error: focus_to_kanata.py not found in current directory!"
    exit 1
fi

# 3. Link Configuration
if [ -f "$PROJECT_ROOT/config.toml" ]; then
    ln -sf "$PROJECT_ROOT/config.toml" "$CONFIG_DIR/config.toml"
    echo "✅ Symlink created: $CONFIG_DIR/config.toml"
else
    echo "⚠️  Warning: config.toml not found. Create it to avoid errors."
fi

# 4. Link KWin Script Template
if [ -f "$PROJECT_ROOT/kwin_script.js" ]; then
    ln -sf "$PROJECT_ROOT/kwin_script.js" "$STATE_DIR/kwin_script.js"
    echo "✅ Symlink created: $STATE_DIR/kwin_script.js"
fi

# 5. Setup Systemd Service with absolute path
if [ -f "$PROJECT_ROOT/kwanata.service" ]; then
    ln -sf "$PROJECT_ROOT/kwanata.service" "$SERVICE_DIR/kwanata.service"
    echo "✅ Symlink created: $SERVICE_DIR/kwanata.service"
fi

# 6. Reload Systemd
systemctl --user daemon-reload

echo "--------------------------------------------------"
echo "🚀 Development environment ready!"
echo "Note: Any changes to your local files will be live on next service restart."
echo "Command: systemctl --user restart kwanata.service"
echo "--------------------------------------------------"
