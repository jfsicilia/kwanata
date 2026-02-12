# KWanata

A bridge between KDE Plasma's window focus events and the [Kanata](https://github.com/jtroo/kanata) keyboard remapper. KWanata switches Kanata layers and activates virtual keys based on the currently focused application.

## How it works

```
KWin --> kwin_script.js (injected at runtime) --DBus--> focus_to_kanata.py --TCP--> Kanata
```

1. On startup, `focus_to_kanata.py` dynamically injects a JavaScript file into KWin via the KWin Scripting DBus API.
2. The injected script listens for `windowActivated` and `captionChanged` signals and sends window properties (pid, name, class, caption) over DBus.
3. The Python service matches window info against rules in `config.toml` and sends layer/virtual-key commands to Kanata over a persistent TCP connection.

## Requirements

- KDE Plasma 5 or 6 (KWin)
- [Kanata](https://github.com/jtroo/kanata) running with TCP server enabled (Default port `-p 10101`)
- Python 3.11+ (uses `tomllib`)
- System packages (not pip):

```bash
# Fedora
sudo dnf install python3-gobject
sudo dnf install python3-dbus
```

```bash
# Ubuntu
sudo apt install python3-gi
sudo apt install python3-dbus
```

## Quick start

1. Start Kanata with the TCP server enabled:

   ```bash
   # NOTE: Choose the port at own discretion.
   kanata -p 10101
   ```

2. Run KWanata:

   ```bash
   python3 focus_to_kanata.py --port 10101 -c config.toml
   ```

   The service will automatically inject the KWin script, listen for window events, and forward matching rules to Kanata. Use `-v` for debug logging.

3. Switch between windows -- Kanata layers and virtual keys will change according to your rules in `config.toml`.

4. Press `Ctrl+C` to stop. The injected KWin script is automatically unloaded on shutdown.

## Configuration

Rules are defined in `config.toml` as an ordered list of `[[app]]` entries. First match wins.

```toml
[[app]]
name = "chrome"                    # regex matched against window resource name
virtual_keys = ["vk_chrome"]

[[app]]
name = "foot"
caption = "^tmux.*(N|n)vim$"       # regex matched against window title
virtual_keys = ["vk_nvim", "vk_tmux"]

[[app]]
name = "foot"
caption = "^Zellij"
virtual_keys = ["vk_zellij"]

[[app]]
name = "foot|konsole"
virtual_keys = ["vk_foot"]
```

Each rule can specify:

| Field          | Type     | Description                                  |
| -------------- | -------- | -------------------------------------------- |
| `name`         | regex    | Window resource name (e.g. `chrome`, `foot`) |
| `class`        | regex    | Window resource class                        |
| `caption`      | regex    | Window title / caption                       |
| `layer`        | string   | Kanata layer to activate                     |
| `virtual_keys` | string[] | Kanata virtual keys to press                 |

All fields are optional. Omitted fields match everything (wildcard). At least one of `layer` or `virtual_keys` should be specified for a rule to have an effect.

## CLI options

```
usage: focus_to_kanata.py [-h] [--host HOST] [--port PORT]
                          [-l DEFAULT_LAYER] [-c CONFIG]
                          [--kwin-script KWIN_SCRIPT] [-v]

  --host HOST             Kanata host (default: 127.0.0.1)
  --port PORT             Kanata port (default: 10101)
  -l, --default_layer     Fallback layer when no rule matches (default: default_layer)
  -c, --config            Path to TOML rules file (default: config.toml)
  --kwin-script           Path to KWin JS file to inject (default: kwin_script.js)
  -v, --verbose           Enable debug logging
```

## Running as a systemd service

A unit file is provided at `kwanata.service`. Edit the paths to match your installation, then:

```bash
# Copy or symlink the unit file
cp kwanata.service ~/.config/systemd/user/kwanata.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable kwanata.service
systemctl --user start kwanata.service

# Check logs
journalctl --user -u kwanata.service -f
```

The service is configured to start after `kanata.service` and stop when Kanata stops (`PartOf=kanata.service`).

## Debugging

```bash
# Monitor DBus messages to KWanata
dbus-monitor "destination=com.pyroflexia.KWanata"

# Tail KWin script logs
journalctl --user -u plasma-kwin_wayland.service -f -n 100

# Query window info interactively
qdbus6 org.kde.KWin /KWin org.kde.KWin.queryWindowInfo
```

## Project structure

```
focus_to_kanata.py   # Python DBus service (main entry point)
kwin_script.js       # KWin script (dynamically injected at runtime)
config.toml          # App-matching rules
kwanata.service      # systemd user unit file
```

## License

MIT

## Inspiration and acknowledgment

This tool could not be possible without these other tools:

- [kanata](https://github.com/jtroo/kanata)
- [FocusNotifier](https://github.com/c-massie/FocusNotifier)
- [hyprkan](https://github.com/haithium/hyprkan)
- [jumpkwapp](https://github.com/jasalt/jumpkwapp)
- [ww-run-or-raise](https://github.com/academo/ww-run-raise)
- [kdotools](https://github.com/tvidal-net/kdotool)
